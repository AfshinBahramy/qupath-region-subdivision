// Synthetic-only checks using QuPath 0.6.0's libraries; no project or slide is opened.
import qupath.lib.io.PathIO
import java.nio.file.Files
import qupath.lib.scripting.QP
import qupath.lib.images.ImageData
import qupath.lib.images.servers.WrappedBufferedImageServer
import qupath.lib.objects.PathObjects
import qupath.lib.objects.classes.PathClass
import qupath.lib.gui.tools.ColorToolsFX
import qupath.lib.roi.GeometryTools
import qupath.lib.regions.ImagePlane
import java.awt.image.BufferedImage
import qupath.lib.io.GsonTools
import org.locationtech.jts.geom.Coordinate
import org.locationtech.jts.geom.GeometryFactory

if (args.length < 1 || args.length > 2)
    throw new IllegalArgumentException('Pass REPOSITORY and optionally PYTHON_EXECUTABLE for full synthetic checks.')
def repo = new File(args[0])
def loader = new GroovyClassLoader(this.class.classLoader)
loader.parseClass(new File(repo, 'qupath/subdivide_auto.groovy'))
def manual = loader.parseClass(new File(repo, 'qupath/subdivide_manual_centerline.groovy')).getDeclaredConstructor().newInstance()
def readObjects = { String name ->
    def objects
    new File(repo, name).withInputStream { stream -> objects = PathIO.readObjectsFromGeoJSON(stream) }
    objects
}
def source = readObjects('examples/input/synthetic_band.geojson')[0].getROI().getGeometry()
def objects = readObjects('examples/output/synthetic_band_segments.geojson')
assert objects.size() == 5
assert objects.every { it.isAnnotation() && it.getROI().getGeometry().isValid() && it.getROI().getArea() > 0 }
def joined = objects[0].getROI().getGeometry()
objects.drop(1).each { joined = joined.union(it.getROI().getGeometry()) }
def roundTripError = joined.symDifference(source).getArea() / source.getArea()
println("QuPath GeoJSON round-trip relative area difference: ${roundTripError}")
assert roundTripError <= 1e-4 : 'QuPath round-trip coverage exceeded 0.01% area tolerance'

def lineRaw = GsonTools.getInstance().fromJson(new File(repo, 'examples/centerline.geojson').text, Map.class)
def factory = new GeometryFactory()
def coords = lineRaw.geometry.coordinates.collect { new Coordinate(it[0] as double, it[1] as double) } as Coordinate[]
def line = factory.createLineString(coords)
def segments = manual.dividePolygonAlongLine(source, line, 5, factory)
assert segments.size() == 5
joined = segments[0]
segments.eachWithIndex { segment, i ->
    assert segment.isValid() && segment.getArea() > 0
    if (i > 0) joined = joined.union(segment)
    for (int j = i + 1; j < segments.size(); j++)
        assert segment.intersection(segments[j]).getArea() <= source.getArea() * 1e-8
}
def manualError = joined.symDifference(source).getArea() / source.getArea()
println("Manual helper relative coverage difference: ${manualError}")
assert manualError <= 1e-8 : 'Manual helper coverage exceeded tolerance'
println('PASS: both scripts compile; Python export parses; manual helper creates a complete non-overlapping five-part synthetic partition.')

// Optional full script execution on an in-memory synthetic image.
// Configure the two path fields in memory; production scripts remain generic.
if (args.length == 2) {
    assert repo.name.contains('fixture') : 'Use a copied fixture repository for full checks.'
    assert !new File(repo, 'runs').exists() : 'Use a fresh fixture without existing runs.'
    assert System.getProperty('java.util.prefs.userRoot') : 'Set an isolated java.util.prefs.userRoot for this test.'
    def template = new File(repo, 'qupath/subdivide_auto.groovy').text
    // Single-quoted Groovy literals preserve Windows backslashes, apostrophes and dollar signs.
    def literal = { String value -> "'" + value.replace('\\', '\\\\').replace("'", "\\'") + "'" }
    int scriptNumber = 0
    def configured = { String python, String script ->
        def text = template.replace("def PYTHON_EXECUTABLE = ''", 'def PYTHON_EXECUTABLE = ' + literal(python))
                           .replace("def SUBDIVISION_SCRIPT = ''", 'def SUBDIVISION_SCRIPT = ' + literal(script))
        loader.parseClass(text, "AutomaticCheck${++scriptNumber}.groovy").getDeclaredConstructor().newInstance()
    }
    def pythonPath = new File(args[1]).absolutePath
    def scriptPath = new File(repo, 'segment_polygon.py').absolutePath
    def image = new BufferedImage(2300, 2300, BufferedImage.TYPE_INT_RGB)
    def server = new WrappedBufferedImageServer('synthetic-image', image)
    def imageData = new ImageData(server)
    def original = PathObjects.createAnnotationObject(GeometryTools.geometryToROI(source, ImagePlane.getDefaultPlane()))
    original.setName('CA1')
    original.setPathClass(PathClass.getInstance('Hippocampus', 0x8844AA))
    original.setColor(0)  // Explicit black must not fall back to the class color.
    imageData.getHierarchy().addObject(original)
    QP.setBatchProjectAndImage(null, imageData)
    QP.selectObjects([original])
    // Bad settings fail before any exports or hierarchy changes.
    ['', new File(repo, 'missing-python').path].each { badPython ->
        try { configured(badPython, scriptPath).run(); assert false }
        catch (IllegalArgumentException expected) { assert expected.message.contains('PYTHON_EXECUTABLE') }
    }
    ['', new File(repo, 'missing-script.py').path].each { badScript ->
        try { configured(pythonPath, badScript).run(); assert false }
        catch (IllegalArgumentException expected) { assert expected.message.contains('SUBDIVISION_SCRIPT') }
    }
    assert !new File(repo, 'runs').exists()
    assert imageData.getHierarchy().getAnnotationObjects().size() == 1
    def automatic = configured(pythonPath, scriptPath)
    def checkMetadata = { parent, children, String prefix ->
        assert children.size() == 5
        assert children.collect { it.getName() }.toSet() == (1..5).collect { "${prefix}-${it}".toString() }.toSet()
        assert children.every { it.getPathClass().is(parent.getPathClass()) }
        assert children.every { it.getColor() == parent.getColor() }
        assert children.every { ColorToolsFX.getDisplayedColorARGB(it) == ColorToolsFX.getDisplayedColorARGB(parent) }
    }
    automatic.run()
    assert imageData.getHierarchy().getAnnotationObjects().size() == 6
    assert imageData.getHierarchy().getAnnotationObjects().contains(original)
    checkMetadata(original, imageData.getHierarchy().getAnnotationObjects().findAll { it != original }, 'CA1')
    // An empty annotation name falls back to the class, with inherited class color.
    original.setName('   ')
    original.setPathClass(PathClass.getInstance('Subiculum', 0x22AA55))
    original.setColor(null)
    def beforeSecond = imageData.getHierarchy().getAnnotationObjects().toSet()
    QP.selectObjects([original])
    automatic.run()
    assert imageData.getHierarchy().getAnnotationObjects().size() == 11
    checkMetadata(original, imageData.getHierarchy().getAnnotationObjects().findAll { !beforeSecond.contains(it) }, 'Subiculum')
    def base = new File(repo, 'runs')
    def folders = base.listFiles().findAll { it.isDirectory() && it.name.startsWith('subdivision-') }
    assert folders.size() == 2
    assert folders.every { new File(it, 'output/region_001_segments.geojson').isFile() }
    def previousOutputs = folders.collectEntries { folder ->
        def file = new File(folder, 'output/region_001_segments.geojson')
        [(file.path): file.text]
    }
    // A process failure, missing second result, or wrong segment count imports nothing.
    def twoParents = [original, PathObjects.createAnnotationObject(original.getROI())]
    imageData.getHierarchy().addObject(twoParents[1])
    def beforeFailure = imageData.getHierarchy().getAnnotationObjects().size()
    def badRepo = Files.createTempDirectory(repo.toPath(), 'bad-output-').toFile()
    def fakeScript = new File(badRepo, 'segment_polygon.py')
    def fixturePayload = new File(repo, 'examples/output/synthetic_band_segments.geojson').text
    fakeScript.text = "import sys; print('intentional test failure'); sys.exit(2)\n"
    QP.selectObjects([original])
    try { configured(pythonPath, fakeScript.path).run(); assert false }
    catch (IllegalStateException expected) { assert expected.message.contains('Python subdivision failed') }
    assert imageData.getHierarchy().getAnnotationObjects().size() == beforeFailure
    // Use a JSON literal compatible with Python rather than interpolating source paths.
    fakeScript.text = 'import pathlib,sys,json\np=pathlib.Path(sys.argv[2]);p.mkdir()\npayload=json.loads(' + GsonTools.getInstance().toJson(GsonTools.getInstance().toJson(fixturePayload)) + ')\n(p/"region_001_segments.geojson").write_text(payload)\n'
    QP.selectObjects(twoParents)
    try { configured(pythonPath, fakeScript.path).run(); assert false }
    catch (IllegalStateException expected) { assert expected.message.contains('Missing or unreadable') }
    assert imageData.getHierarchy().getAnnotationObjects().size() == beforeFailure
    fakeScript.text = 'import pathlib,sys,json\np=pathlib.Path(sys.argv[2]);p.mkdir()\npayload=json.loads(' + GsonTools.getInstance().toJson(GsonTools.getInstance().toJson(fixturePayload)) + ')\ndata=json.loads(payload);data["features"]=data["features"][:1]\n(p/"region_001_segments.geojson").write_text(json.dumps(data))\n'
    QP.selectObjects([original])
    try { configured(pythonPath, fakeScript.path).run(); assert false }
    catch (IllegalStateException expected) { assert expected.message.contains('Expected 5 valid') }
    assert imageData.getHierarchy().getAnnotationObjects().size() == beforeFailure
    // Previous successful run files survive all failures.
    assert previousOutputs.every { path, content -> new File(path).text == content }
    assert imageData.getHierarchy().getAnnotationObjects().containsAll(twoParents)

    // Named, unclassified parents retain null PathClass and their own/default color.
    def namedParents = ['Custom band', 'Unclassified band'].collect { name ->
        def parent = PathObjects.createAnnotationObject(original.getROI())
        parent.setName(name)
        parent
    }
    namedParents[0].setColor(0x336699)
    imageData.getHierarchy().addObjects(namedParents)
    def beforeNamed = imageData.getHierarchy().getAnnotationObjects().toSet()
    fakeScript.text = 'import pathlib,sys,json\np=pathlib.Path(sys.argv[2]);p.mkdir()\npayload=json.loads(' + GsonTools.getInstance().toJson(GsonTools.getInstance().toJson(fixturePayload)) + ')\nfor source in pathlib.Path(sys.argv[1]).glob("*.geojson"):\n (p/(source.stem+"_segments.geojson")).write_text(payload)\n'
    QP.selectObjects(namedParents)
    configured(pythonPath, fakeScript.path).run()
    def namedChildren = imageData.getHierarchy().getAnnotationObjects().findAll { !beforeNamed.contains(it) }
    assert namedChildren.size() == 10
    namedParents.each { parent ->
        checkMetadata(parent, namedChildren.findAll { it.getName().startsWith(parent.getName() + '-') }, parent.getName())
        assert parent.getPathClass() == null
    }
    assert imageData.getHierarchy().getAnnotationObjects().containsAll(namedParents)
    println('PASS: annotation-name precedence, class-name fallback, original PathClass identity, explicit/class/default display colors and named unclassified parents.')

    QP.resetBatchProjectAndImage()
    imageData.close()

    server = new WrappedBufferedImageServer('synthetic-manual-image', image)
    imageData = new ImageData(server)
    original = PathObjects.createAnnotationObject(GeometryTools.geometryToROI(source, ImagePlane.getDefaultPlane()))
    def centerlineObject = PathObjects.createAnnotationObject(GeometryTools.geometryToROI(line, ImagePlane.getDefaultPlane()))
    imageData.getHierarchy().addObjects([original, centerlineObject])
    QP.setBatchProjectAndImage(null, imageData)
    QP.selectObjects([original, centerlineObject])
    // Raw automatic endpoints can sit just outside the rounded QuPath polygon.
    // The manual workflow correctly refuses that input without adding objects.
    try {
        manual.run()
        throw new AssertionError('Expected the outside-endpoint guard to reject this line.')
    } catch (IllegalStateException expected) {
        assert expected.message.contains('Centerline must be within')
        assert imageData.getHierarchy().getAnnotationObjects().size() == 2
    }
    // A manually drawn interior line has endpoints inset from the boundary.
    def interiorLine = factory.createLineString(coords[3..(coords.length - 4)] as Coordinate[])
    centerlineObject.setROI(GeometryTools.geometryToROI(interiorLine, ImagePlane.getDefaultPlane()))
    manual.run()
    assert imageData.getHierarchy().getAnnotationObjects().size() == 7
    assert imageData.getHierarchy().getAnnotationObjects().containsAll([original, centerlineObject])
    QP.resetBatchProjectAndImage()
    imageData.close()
    println('PASS: two-path automatic wrapper (two independent runs), invalid settings, process failure, missing result, wrong count, and unchanged manual workflow; originals and existing outputs preserved.')
}
