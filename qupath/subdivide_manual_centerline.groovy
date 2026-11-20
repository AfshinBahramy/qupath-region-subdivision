/**
 * QuPath Script: Polygon Division using Manual Centerline
 *
 * This script:
 * 1. Takes a selected POLYGON annotation
 * 2. Uses a POLYLINE annotation as the centerline (must be inside the polygon)
 * 3. Divides the polygon into N segments at equal centerline intervals with perpendicular cuts
 * 4. Creates new annotations for each segment
 *
 * Usage:
 * 1. Create your polygon annotation (e.g., CA1 or Subiculum region)
 * 2. Draw a polyline annotation inside it representing the centerline
 * 3. Select BOTH annotations (polygon and polyline)
 * 4. Run this script
 *
 * Note: The polyline should run through the center of the polygon from one end to the other
 */

import static qupath.lib.gui.scripting.QPEx.*
import qupath.lib.objects.PathAnnotationObject
import qupath.lib.roi.ROIs
import qupath.lib.roi.GeometryTools
import qupath.lib.regions.ImagePlane
import org.locationtech.jts.geom.*
import org.locationtech.jts.linearref.LengthIndexedLine
import org.locationtech.jts.algorithm.Angle

// ============ CONFIGURATION ============
def NUM_SEGMENTS = (System.getenv('CA1_SUBDIVISION_SEGMENTS') ?: '5').toInteger()
if (NUM_SEGMENTS < 2)
    throw new IllegalArgumentException('At least two segments are required.')
// =======================================

def imageData = getCurrentImageData()
def hierarchy = imageData.getHierarchy()
def selected = hierarchy.getSelectionModel().getSelectedObjects()

// Separate polygons and polylines (convert to lists explicitly)
def polygons = selected.findAll { it.isAnnotation() && it.getROI().isArea() } as List
def polylines = selected.findAll { it.isAnnotation() && it.getROI().isLine() && !it.getROI().isArea() } as List

if (polygons.isEmpty()) {
    println("ERROR: Please select at least one polygon annotation!")
    println("You selected: ${selected.size()} object(s)")
    return
}

if (polylines.isEmpty()) {
    println("ERROR: Please select at least one polyline annotation to use as centerline!")
    println("You selected: ${polygons.size()} polygon(s) but no polyline")
    println("\nTo create a polyline:")
    println("1. Click the 'Polyline' tool in the toolbar")
    println("2. Draw a line through the center of your polygon")
    println("3. Select both the polygon and polyline")
    println("4. Run this script again")
    return
}

println("Processing ${polygons.size()} polygon(s) with ${polylines.size()} centerline(s)...")

def factory = new GeometryFactory()
def newAnnotations = []

// Process each polygon with its closest polyline
polygons.each { polygonAnnotation ->
    try {
        def roi = polygonAnnotation.getROI()
        def geometry = roi.getGeometry()
        def polygon = geometry instanceof Polygon ? geometry : null

        if (polygon == null || !polygon.isValid() || polygon.isEmpty() || polygon.getNumInteriorRing() != 0)
            throw new IllegalArgumentException('Select a valid simple Polygon without holes.')
        def plane = roi.getImagePlane()

        // Find the best matching polyline (closest or contained within)
        def centerlineAnnotation = findBestCenterline(polygon, polylines)

        if (centerlineAnnotation == null) {
            println("No suitable centerline found for polygon")
            return
        }

        def centerlineGeom = centerlineAnnotation.getROI().getGeometry()
        def centerline = centerlineGeom instanceof LineString ? centerlineGeom : null

        if (centerline == null || !centerline.isValid() || centerline.getLength() <= 0)
            throw new IllegalArgumentException('Centerline must be a valid non-zero LineString.')
        if (!polygon.covers(centerline) || centerlineAnnotation.getROI().getImagePlane() != plane)
            throw new IllegalArgumentException('Centerline must be within the polygon on the same image plane.')

        println("\nProcessing: ${polygonAnnotation.getPathClass()?.getName() ?: 'Unnamed'}")
        println("  Polygon area: ${polygon.getArea()}")
        println("  Centerline length: ${centerline.getLength()}")

        // Divide polygon into segments
        def segments = dividePolygonAlongLine(polygon, centerline, NUM_SEGMENTS, factory)

        if (segments.size() != NUM_SEGMENTS)
            throw new IllegalStateException("Expected ${NUM_SEGMENTS} segments, got ${segments.size()}; no annotations added.")
        def tolerance = polygon.getArea() * 1e-8
        def combined = segments[0]
        segments.eachWithIndex { segment, i ->
            if (segment.isEmpty() || !segment.isValid() || segment.getArea() <= 0)
                throw new IllegalStateException('Subdivision produced an invalid or empty segment.')
            for (int j = i + 1; j < segments.size(); j++) {
                if (segment.intersection(segments[j]).getArea() > tolerance)
                    throw new IllegalStateException('Subdivision contains overlapping segments.')
            }
            if (i > 0) combined = combined.union(segment)
        }
        if (combined.symDifference(polygon).getArea() > tolerance)
            throw new IllegalStateException('Subdivision does not cover the original polygon.')

        println("  Created ${segments.size()} segments")

        // Create annotations for each segment
        def baseClass = polygonAnnotation.getPathClass()
        def baseName = baseClass?.getName() ?: "Region"

        // Determine if this is CA1 or Subiculum for proper naming
        if (baseName.contains("CA1")) {
            baseName = "CA1"
        } else if (baseName.contains("Subiculum")) {
            baseName = "Subiculum"
        }

        segments.eachWithIndex { segment, idx ->
            def segmentROI = GeometryTools.geometryToROI(segment, plane)
            def segmentName = "${baseName}-${idx + 1}"
            def segmentAnnotation = new PathAnnotationObject(segmentROI, baseClass)
            segmentAnnotation.setName(segmentName)
            newAnnotations << segmentAnnotation
        }

        println("  ✓ Success!")

    } catch (Exception e) {
        throw new IllegalStateException("Subdivision failed; no new annotations added: ${e.getMessage()}", e)
    }
}

// Add new annotations to hierarchy
if (!newAnnotations.isEmpty()) {
    hierarchy.addObjects(newAnnotations)
    println("\n========================================")
    println("✓ Complete! Created ${newAnnotations.size()} segment annotations")
    println("\nOriginal annotations are still present.")
    println("You can delete them manually if desired.")
    println("========================================")
} else {
    println("\n✗ No segments were created. Check the errors above.")
}

// ============ HELPER FUNCTIONS ============

/**
 * Find the best centerline for a polygon
 */
def findBestCenterline(Polygon polygon, List polylines) {
    // First, try to find a polyline that's inside the polygon
    def contained = polylines.find { polyline ->
        def geom = polyline.getROI().getGeometry()
        polygon.contains(geom) || polygon.covers(geom)
    }

    if (contained != null) {
        return contained
    }

    // If none contained, find the closest one
    def minDist = Double.MAX_VALUE
    def closest = null

    polylines.each { polyline ->
        def geom = polyline.getROI().getGeometry()
        def dist = polygon.distance(geom)
        if (dist < minDist) {
            minDist = dist
            closest = polyline
        }
    }

    return closest
}

/**
 * Divide polygon into N segments along centerline
 */
def dividePolygonAlongLine(Polygon polygon, LineString centerline, int numSegments, GeometryFactory factory) {
    if (numSegments < 2) return [polygon]

    def indexedLine = new LengthIndexedLine(centerline)
    def totalLength = centerline.getLength()
    def segments = []
    def currentPoly = polygon

    println("  Creating ${numSegments - 1} perpendicular cut lines...")

    // Create perpendicular cuts at regular intervals
    for (int i = 1; i < numSegments; i++) {
        def distance = (i * totalLength) / numSegments

        // Get point and direction at this distance
        def point = indexedLine.extractPoint(distance)
        def tangent = getTangentVector(indexedLine, distance, totalLength)

        if (tangent == null) {
            println("    Warning: Could not compute tangent at distance ${distance}")
            continue
        }

        // Create perpendicular line
        def perpLine = createPerpendicularLine(point, tangent, polygon.getEnvelopeInternal(), factory)

        // Split the polygon
        def parts = splitPolygon(currentPoly, perpLine, factory)

        if (parts.size() == 2) {
            // Determine which part comes first along the centerline
            def centroid1 = parts[0].getCentroid().getCoordinate()
            def centroid2 = parts[1].getCentroid().getCoordinate()

            // Project centroids onto tangent direction
            def proj1 = centroid1.x * tangent.x + centroid1.y * tangent.y
            def proj2 = centroid2.x * tangent.x + centroid2.y * tangent.y

            if (proj1 < proj2) {
                segments << parts[0]
                currentPoly = parts[1]
            } else {
                segments << parts[1]
                currentPoly = parts[0]
            }

            println("    Cut ${i}/${numSegments - 1} successful")
        } else {
            println("    Warning: Cut ${i} produced ${parts.size()} parts instead of 2")
        }
    }

    // Add the final segment
    segments << currentPoly

    // Reverse to match your Python output
    // (so segment 1 is at the end, segment 5 is at the beginning)
    return segments.reverse()
}

/**
 * Get tangent vector at distance along line
 */
def getTangentVector(LengthIndexedLine indexedLine, double distance, double totalLength) {
    def epsilon = Math.min(1.0, totalLength * 0.01)

    def d1 = Math.max(0, distance - epsilon)
    def d2 = Math.min(totalLength, distance + epsilon)

    def p1 = indexedLine.extractPoint(d1)
    def p2 = indexedLine.extractPoint(d2)

    def dx = p2.x - p1.x
    def dy = p2.y - p1.y
    def length = Math.sqrt(dx * dx + dy * dy)

    if (length < 1e-9) return null

    return [x: dx / length, y: dy / length]
}

/**
 * Create perpendicular line through a point
 */
def createPerpendicularLine(Coordinate point, Map tangent, Envelope envelope, GeometryFactory factory) {
    // Perpendicular vector (rotate tangent 90 degrees)
    def nx = -tangent.y
    def ny = tangent.x

    // Make line long enough to definitely cross the polygon
    def diagonal = Math.sqrt(
        Math.pow(envelope.getWidth(), 2) +
        Math.pow(envelope.getHeight(), 2)
    ) * 2.0

    def p1 = new Coordinate(point.x - nx * diagonal, point.y - ny * diagonal)
    def p2 = new Coordinate(point.x + nx * diagonal, point.y + ny * diagonal)

    return factory.createLineString([p1, p2] as Coordinate[])
}

/**
 * Split polygon by line using polygonizer
 */
def splitPolygon(Polygon polygon, LineString line, GeometryFactory factory) {
    try {
        // Union the polygon boundary with the cutting line
        def union = polygon.getExteriorRing().union(line)

        // Polygonize to get separate regions
        def polygonizer = new org.locationtech.jts.operation.polygonize.Polygonizer()
        polygonizer.add(union)

        def polygons = polygonizer.getPolygons()
        def result = []

        // Keep only polygons that are inside the original polygon
        polygons.each { poly ->
            if (polygon.contains(poly.getInteriorPoint())) {
                result << poly
            }
        }

        return result

    } catch (Exception e) {
        println("    Error in split: ${e.getMessage()}")
        return []
    }
}

println("\n=== Script finished ===")
