# Oblique Axonometric Cameras for IngeTrazo

Cabinet and Military oblique projections for [IngeTrazo](https://ingetrazo.com/): keep one plane at true size, draw the receding axis at 30°, 45° or 60°, and control how much the oblique faces are foreshortened.

![License](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)
![Platform](https://img.shields.io/badge/platform-IngeTrazo%200.x-lightgrey)
![Python](https://img.shields.io/badge/python-3.9%2B-3776AB)

| Cabinet — ZX plane | Cabinet — YZ plane | Military — XY plan |
| --- | --- | --- |
| ![Cabinet ZX](docs/images/cabinet-zx.png) | ![Cabinet YZ](docs/images/cabinet-yz.png) | ![Military XY](docs/images/military-xy.png) |

<img width="689" height="567" alt="oblique" src="https://github.com/user-attachments/assets/4e97fc5f-d24f-4848-b304-2d528af39bd8" />



## Features

- **14 one-click presets** — 12 Cabinet (XZ, ZX, YZ, ZY × 60°, 45°, 30°) and 2 Military (XY, YX).
- **True-size plane of your choice** — keep a front or side face undistorted (XZ, ZX, YZ, ZY).
- **Adjustable reduction factor** for the oblique faces — `0.5` is the classic Cabinet value, `1.0` gives a Cavalier projection.
- **Receding side switch** — send the depth to the right or to the left.
- **Automatic framing** — the shear is centred on the model bounds, so the drawing does not drift off screen or clip.
- **Dockable panel and menu entries** — presets, custom settings, frame, and clear.
- **View-only** — the model is never modified, so these cameras create no geometry and no undo steps.

## The projections

### Cabinet

A vertical plane is drawn in **true size**: its two axes stay horizontal and vertical on screen, with their real lengths and a right angle between them. The third axis — perpendicular to that plane — **recedes** at 30°, 45° or 60° and is shortened by the reduction factor (typically **0.5**).

In this plugin the true-size plane can be:

| Plane | Drawn with |
| --- | --- |
| `XZ` | X across, Z up (front) |
| `ZX` | Z across, X up (side) |
| `YZ` | Y across, Z up (side) |
| `ZY` | Z across, Y up (side) |

### Military

The **horizontal plan** (XY or YX) is kept at true size and **rotated 45°** on screen, so its two axes run at 45° and 135° and remain **90° apart**. The vertical axis is drawn vertically, shortened by the reduction factor (0.5 by default).

### Cavalier

Cabinet with a reduction factor of **1.0**: the receding axis is drawn at full length. It is easy to produce and measure, but usually looks elongated, which is why Cabinet halves the depth.

## Why a normal camera cannot produce these views

A perspective or orthographic camera only **rotates and translates** the world. Both are rigid transforms: they cannot keep one plane at true size while drawing the perpendicular axis at an arbitrary angle and an arbitrary length. Under a rotation, the screen angles and the foreshortening of the three axes are completely determined by the view direction — there is no degree of freedom left to choose `45°` with `0.5×`.

Cabinet, Cavalier and Military are therefore **drawing conventions**, not real views: they deliberately **distort** the object so that it fits the sheet and stays measurable. The plugin reproduces that distortion mathematically instead of rotating the camera.

## How the distortion is simulated

When an oblique mode is active, the plugin injects a **shear** into the camera's model-to-view transform and forces the projection to be **orthographic**:

```
S = I + w nᵀ
w = f · (cos α · h + sin α · v)
```

- `h`, `v` — the two axes of the true-size plane; they are left untouched.
- `n` — the axis perpendicular to that plane (the receding axis).
- `α` — the drawing angle (30°, 45° or 60° for Cabinet; the plan rotation for Military).
- `f` — the reduction factor.

For a point `P` with depth `d = n · P`, the screen coordinates become:

```
u' = h · P + f · cos α · d
v' = v · P + f · sin α · d
```

Consequences:

- points on the true-size plane (`d = 0`) keep their exact position, length and right angles;
- the receding axis `n` becomes `n + w`, which projects as a segment of length `f` at angle `α`;
- the depth along `n` is preserved (`n · S P = n · P`), so the depth buffer, hidden-line removal and picking keep working.

The shear is applied around the **centre of the model bounds** and the view is reframed afterwards, which prevents drift and clipping. While the mode is active, `projection_mode()` reports `"parallel"` and perspective/two-point are disabled.

> Any camera operation that changes the view direction — orbit, `look_from`, `set_view`, `snap_iso`, toggling the projection — **clears the oblique mode**, because the true-size plane is tied to the preset. Reapply the preset after rotating.

## Installation

1. Download or copy **`oblique_axonometric_cameras.py`**.
2. Put it in your IngeTrazo user plugins folder:
   - **Windows:** `%APPDATA%\ingetrazo\plugins\`
   - **Linux:** `$XDG_DATA_HOME/ingetrazo/plugins/` (usually `~/.local/share/ingetrazo/plugins/`)
   - **macOS / other:** use the folder opened by **Extensions ▸ Open plugins folder**.
3. Restart IngeTrazo — plugins are discovered at startup.

Command-line install:

```powershell
# Windows (PowerShell)
Copy-Item .\oblique_axonometric_cameras.py "$env:APPDATA\ingetrazo\plugins\"
```

```bash
# Linux
cp oblique_axonometric_cameras.py ~/.local/share/ingetrazo/plugins/
```

After restarting, the extension appears under **Extensions ▸ Oblique Axonometric Cameras**.

## Usage

Open **Extensions ▸ Oblique Axonometric Cameras**:

- pick one of the **14 presets** directly from the menu, or
- open **Open Oblique Axonometric Cameras panel...** for full control.

### Panel controls

| Control | What it does |
| --- | --- |
| **Preset** | Cabinet 30°/45°/60° on XZ/ZX/YZ/ZY, or Military 45° on XY/YX. |
| **True-size plane** | Sets the plane that stays undistorted; choosing `XY`/`YX` switches to the Military family. |
| **Angle** | Cabinet: angle of the receding axis. Military: rotation of the plan (default 45°). |
| **Reduction factor** | Foreshortening of the oblique faces, `0.0`–`2.0` (default `0.5`; `1.0` = Cavalier). |
| **Receding side** | Draw the depth to the **right** or to the **left**. |
| **Frame the model after applying** | Zoom-extents the sheared drawing (on by default). |

Buttons:

- **Apply preset** — applies the selected preset with its own settings (0.5, right side).
- **Apply settings** — applies the current values of the form (custom plane, angle, factor and side).
- **Frame model** — fits the model again in the current oblique view.
- **Clear oblique** — returns to a standard parallel projection, keeping the view direction.

The **Details** label describes the combination currently selected in the form, for example:

> Cabinet: true-size plane XZ (X horizontal, Z vertical). Receding axis +Y at 45°, length 0.5x. Receding side: right side.

### Presets and their keys

Cabinet presets use `cabinet_<angle>_<plane>` (factor `0.5`, receding right):

| Plane | 30° | 45° | 60° |
| --- | --- | --- | --- |
| XZ | `cabinet_30_xz` | `cabinet_45_xz` | `cabinet_60_xz` |
| ZX | `cabinet_30_zx` | `cabinet_45_zx` | `cabinet_60_zx` |
| YZ | `cabinet_30_yz` | `cabinet_45_yz` | `cabinet_60_yz` |
| ZY | `cabinet_30_zy` | `cabinet_45_zy` | `cabinet_60_zy` |

Military presets:

| Plane | Key | Description |
| --- | --- | --- |
| XY | `military_45_xy` | Plan rotated 45°, axes at 45°/135° |
| YX | `military_45_yx` | Same, rotated the other way |

## Public API

The module also works as a small library, so other plugins or scripts can drive the camera directly:

```python
apply_oblique_settings(
    viewport,
    plane="XZ",              # "XZ", "ZX", "YZ", "ZY", "XY", "YX"
    angle_deg=45.0,          # receding angle (Cabinet) or plan rotation (Military)
    reduction_factor=0.5,    # 0.5 = Cabinet, 1.0 = Cavalier
    receding_side="right",   # or "left"
    label=None,
    family=None,             # inferred from the plane when omitted
    frame=True,
) -> bool

apply_oblique_preset(viewport, preset_key, frame=True) -> bool
frame_oblique(viewport) -> bool
clear_oblique(viewport) -> bool
preset_description(preset_key) -> str
```

`PRESETS` maps every key to its label, family, plane, angle, factor and receding side; `PRESET_ORDER` gives the display order used by the menu and panel.

## Requirements and compatibility

- IngeTrazo with the Python extension API (`setup(app)`, `add_panel`, `add_menu`), 0.x series.
- Python 3.9+ and PySide6 (bundled with IngeTrazo).
- IngeTrazo is **Z-up** and works in **metres**; the plugin follows the same convention.
- Tested with the current 0.x build on Windows.

Note that the IngeTrazo plugin API is still **unstable** in the 0.x series; a future release may require small updates.

## Limitations

- These are **drawing conventions**, not physically possible views: faces can overlap in ways a real camera would never produce. That is expected.
- The projection is strictly **parallel**; perspective and two-point perspective are disabled while an oblique mode is active.
- Rotating the camera **turns the mode off** by design — reapply the preset.
- The plugin patches the camera instance internally (`view_matrix`, `projection_matrix`, `projection_mode`); a breaking change in `OrbitCamera` would need a matching update here.
- The plugin changes only the **camera**, never the document — no geometry is created and no undo entry is produced.

## Troubleshooting

- **Menu missing:** confirm the file is in the user plugins folder and restart IngeTrazo; check the `ingetrazo.plugins.oblique_axonometric_cameras` logger for a load error.
- **The view snapped back to parallel:** the camera was rotated (orbit, view cube, iso, projection toggle). Reapply the preset.
- **Model off screen or clipped:** click **Frame model**.
- **Axes look wrong:** make sure the reduction factor is the intended one (`0.5` Cabinet, `1.0` Cavalier) and that the chosen true-size plane matches the face you want undistorted.

## Development

`oblique_axonometric_cameras.py` is a single-file plugin with no build step. Version `1.1.0` lives in `__version__`; the module logs through Python's `logging` under `ingetrazo.plugins.oblique_axonometric_cameras`. See `ingetrazo/docs/plugins.md` in the IngeTrazo source for the extension API.

## License

GPL-3.0-or-later, as declared in the source file's SPDX header. Add a matching `LICENSE` file if you publish this plugin as its own repository.
