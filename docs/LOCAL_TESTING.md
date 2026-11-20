# Local testing and troubleshooting

Follow the [README installation commands](../README.md#requirements-and-installation) first. Use Python 3.12 and QuPath 0.6.0. The pinned SciPy 1.17.1 environment requires at least Python 3.11. No GPU or trained model is required.

## Automatic script paths

Edit only the two settings at the top of `qupath/subdivide_auto.groovy` and save your local copy. Replace these example directories with your actual download location.

**Windows:**

```groovy
def PYTHON_EXECUTABLE = 'C:/work/qupath-region-subdivision/.venv/Scripts/python.exe'
def SUBDIVISION_SCRIPT = 'C:/work/qupath-region-subdivision/segment_polygon.py'
```

**macOS:**

```groovy
def PYTHON_EXECUTABLE = '/Users/YOUR_NAME/qupath-region-subdivision/.venv/bin/python'
def SUBDIVISION_SCRIPT = '/Users/YOUR_NAME/qupath-region-subdivision/segment_polygon.py'
```

**Linux:**

```groovy
def PYTHON_EXECUTABLE = '/home/YOUR_NAME/qupath-region-subdivision/.venv/bin/python'
def SUBDIVISION_SCRIPT = '/home/YOUR_NAME/qupath-region-subdivision/segment_polygon.py'
```

Use forward slashes in Windows Groovy strings. Point to the environment's executable, not its folder or activation script. Preserve the virtual-environment path if it is a symlink. No environment variables or terminal launch of QuPath are required.

## Desktop smoke test

1. Open an image in QuPath. You can use a blank image and synthetic annotations for a geometry-only check, or an image you have locally for anatomical inspection. Source tissue images are not included.
2. Draw a simple curved-band polygon without holes. For the automatic method, its ends must be two straight, single boundary edges longer than the individual edges on the densely sampled sides.
3. Give it a name such as `CA1` and optionally a class and custom color. Select it and run `qupath/subdivide_auto.groovy` in **Automate → Show script editor**.
4. Verify five new annotations named `CA1-1` through `CA1-5`, the original classification and displayed color, and preservation of the original. Also try an unnamed classified annotation and a named annotation without a class.
5. Inspect boundaries, alignment and anatomical numbering. Each run should have a fresh `runs/subdivision-*` directory beside `segment_polygon.py`. A second successful run adds another set without replacing existing objects or files.

The automatic name/color behavior has been tested successfully in desktop QuPath. Still verify local installation and paths when moving to another computer. The [QuPath scripting guide](https://qupath.readthedocs.io/en/0.6/docs/scripting/overview.html) describes the script editor.

## Manual-centerline smoke test

Select a simple polygon and an interior polyline on the same image plane. Keep all line vertices and endpoints inside the polygon. Run `qupath/subdivide_manual_centerline.groovy`. Expect five new annotations and preservation of both originals. This route needs no Python. Numbering does not infer anatomical direction; inspect the order before measurements.

## Troubleshooting

- **Missing Python or script:** correct the setting identified by the error. Use full paths and check permissions.
- **Missing NumPy/SciPy/Shapely:** run the selected executable with `-m pip install -r requirements.txt` from the repository directory. On Windows PowerShell, invoke a quoted path using `& 'C:/full/path/python.exe' -m pip install -r requirements.txt`. On macOS/Linux use `'/full/path/bin/python' -m pip install -r requirements.txt`.
- **Dependency installation fails on Python 3.10:** create a new Python 3.12 environment; SciPy 1.17.1 cannot be installed on 3.10.
- **Cannot create a run folder:** keep the repository in a writable location and update `SUBDIVISION_SCRIPT` after moving it.
- **Python subdivision fails:** read the `[python]` console messages and inspect the printed run folder. Failed or incomplete batches add no annotations. Check the two straight end edges and polygon validity; try a manual centerline if appropriate.
- **Misaligned annotations:** use the matching image at its original pixel coordinates, without resizing or registration. Confirm the image plane.
- **A command refuses an existing output:** choose a fresh output directory. Existing files are protected deliberately.

## Optional headless QuPath tests

`tests/verify_qupath.groovy` uses QuPath 0.6.0 libraries and Java 21. Compilation, GeoJSON parsing and manual partition checks need only the repository argument:

```bash
java -Djava.awt.headless=true -cp '/path/to/QuPath/lib/app/*' groovy.ui.GroovyMain tests/verify_qupath.groovy .
```

Replace the classpath with your QuPath installation's library directory; the layout varies by operating system. Headless library checks do not require opening a slide.

For full in-memory integration checks, pass a **fresh copied fixture repository** whose folder name includes `fixture`, followed by the full Python executable path. Include these relative files in the fixture:

```text
segment_polygon.py
qupath/subdivide_auto.groovy
qupath/subdivide_manual_centerline.groovy
examples/input/synthetic_band.geojson
examples/output/synthetic_band_segments.geojson
examples/centerline.geojson
```

Set the JVM option `-Djava.util.prefs.userRoot=/path/to/test-preferences` to isolate preferences used by QuPath's libraries. The automatic workflow itself stores no preferences. The test fills the two script paths in memory, exercises fresh runs and failure cases, and checks metadata preservation; the production scripts remain generic. Use an absolute fixture path and a writable temporary directory. Example on macOS/Linux:

```bash
java -Djava.awt.headless=true -Djava.util.prefs.userRoot=/path/to/test-preferences -cp '/path/to/QuPath/lib/app/*' groovy.ui.GroovyMain tests/verify_qupath.groovy '/path/to/fixture repository' '/path/to/.venv/bin/python'
```

These are optional developer checks. Normal desktop use requires only the installed environment and the two script settings.
