// Automatic curved-region subdivision: select region annotations, then run.
import qupath.lib.io.PathIO
import static qupath.lib.gui.scripting.QPEx.*
import java.nio.file.Files
import org.locationtech.jts.geom.Polygon

// SET THESE TWO FULL PATHS once, then save your local copy of this script.
// Windows: use forward slashes, e.g. 'C:/work/qupath-region-subdivision/.venv/Scripts/python.exe'.
def PYTHON_EXECUTABLE = ''
def SUBDIVISION_SCRIPT = ''  // Full path to segment_polygon.py.

def python = new File(PYTHON_EXECUTABLE).absoluteFile
def script = new File(SUBDIVISION_SCRIPT).absoluteFile
if (!PYTHON_EXECUTABLE || !python.isFile() || !python.canExecute())
    throw new IllegalArgumentException('Set PYTHON_EXECUTABLE at the top to your environment executable: .venv/Scripts/python.exe on Windows or .venv/bin/python on macOS/Linux. Use its full path, not an activation script.')
if (!SUBDIVISION_SCRIPT || !script.isFile())
    throw new IllegalArgumentException('Set SUBDIVISION_SCRIPT at the top to the full path of segment_polygon.py in your downloaded repository.')
if (getCurrentImageData() == null)
    throw new IllegalStateException('Open an image, select its region annotations, and run this script again.')
def anns = getSelectedObjects().findAll { it.isAnnotation() && it.getROI().isArea() }
if (anns.isEmpty())
    throw new IllegalArgumentException('Select at least one curved-region polygon annotation before running this script.')
anns.each { ann ->
    def geometry = ann.getROI().getGeometry()
    if (!(geometry instanceof Polygon) || geometry.isEmpty() || !geometry.isValid() || geometry.getNumInteriorRing() != 0)
        throw new IllegalArgumentException('Only valid simple Polygons without holes are supported. Correct the selected annotation first.')
}

// A unique run folder protects inputs and all earlier outputs.
def base = script.parentFile.toPath().resolve('runs')
def runDir
try {
    Files.createDirectories(base)
    runDir = Files.createTempDirectory(base, 'subdivision-')
} catch (Exception e) {
    throw new IllegalStateException('Cannot create a fresh run folder. Keep the repository in a writable location. ' + e.message, e)
}
def inputDir = Files.createDirectory(runDir.resolve('input'))
def outputDir = runDir.resolve('output')
println("Run files: ${runDir}")
anns.eachWithIndex { ann, idx ->
    exportObjectsToGeoJson([ann], inputDir.resolve(String.format('region_%03d.geojson', idx + 1)).toString(), 'FEATURE_COLLECTION')
}
def proc
try {
    proc = new ProcessBuilder([python.path, script.path, inputDir.toString(), outputDir.toString(),
                               '--segments', '5']).redirectErrorStream(true).start()
} catch (Exception e) {
    throw new IllegalStateException('Could not start Python. Check PYTHON_EXECUTABLE. No new annotations imported. Run files: ' + runDir, e)
}
proc.inputStream.withReader { reader -> reader.eachLine { println('[python] ' + it) } }
if (proc.waitFor() != 0)
    throw new IllegalStateException('Python subdivision failed. Review the Python error above. If a package is missing, install requirements.txt using the selected Python executable. No new annotations imported. Run files: ' + runDir)

// Stage every result before one hierarchy update: a missing/invalid result imports nothing.
def imported = []
anns.eachWithIndex { ann, idx ->
    def file = outputDir.resolve(String.format('region_%03d_segments.geojson', idx + 1)).toFile()
    def objects
    try {
        file.withInputStream { stream -> objects = PathIO.readObjectsFromGeoJSON(stream) }
    } catch (Exception e) {
        throw new IllegalStateException('Missing or unreadable subdivision output: ' + file.name + '. No new annotations imported. Run files: ' + runDir, e)
    }
    if (objects.size() != 5 || objects.any { !it.isAnnotation() || it.getROI() == null || !it.getROI().getGeometry().isValid() || it.getROI().getArea() <= 0 })
        throw new IllegalStateException("Expected 5 valid segment annotations in ${file.name}; no new annotations imported. Run files: ${runDir}")
    def prefix = ann.getName()?.trim() ?: ann.getPathClass()?.toString() ?: 'Region'
    objects.eachWithIndex { obj, segmentIndex ->
        obj.setROI(qupath.lib.roi.GeometryTools.geometryToROI(obj.getROI().getGeometry(), ann.getROI().getImagePlane()))
        obj.setName("${prefix}-${segmentIndex + 1}")
        obj.setPathClass(ann.getPathClass())
        obj.setColor(ann.getColor())  // Null keeps the same class/default display color.
    }
    imported.addAll(objects)
}
addObjects(imported)
fireHierarchyUpdate()
println("Added ${imported.size()} segment annotations. Originals are preserved. Review boundaries and numbering.")
