# SPDX-License-Identifier: GPL-3.0-or-later
"""Oblique axonometric cameras for IngeTrazo: Cabinet and Military.

IngeTrazo's :class:`~core.camera.OrbitCamera` knows perspective and parallel
projections.  An oblique projection (Cabinet, Cavalier, Military) is neither:
the picture plane is parallel to one face of the object, that face keeps its
true size and right angles, and the third axis is drawn at an arbitrary angle
with a chosen reduction factor.  A plain camera cannot produce that view by
rotating alone, so this extension installs a shear in the camera's
model-to-view transform and leaves the projection orthographic.

The shear is

    S = I + w n^T,        w = f (cos(alpha) h + sin(alpha) v)

where ``h`` and ``v`` are the two axes of the true-size plane, ``n`` is the
axis perpendicular to it (the receding axis), ``alpha`` is the drawing angle
and ``f`` is the reduction factor.  Points in the true-size plane
(``n . P = 0``) are untouched; the receding axis ``n`` becomes
``n + w``, whose projection is a segment of length ``f`` at angle ``alpha``.
The depth along ``n`` is preserved (``n . S P = n . P``), so the depth buffer,
hidden-line removal and picking keep working.

Cabinet
    A vertical plane is kept at true size with its two axes horizontal and
    vertical in the view.  The four planes are XZ, ZX, YZ and ZY (the first
    letter is the horizontal axis, the second the vertical one).  The
    complementary axis recedes at 30, 45 or 60 degrees.  The default
    reduction factor is 0.5 (Cabinet); 1.0 gives a Cavalier projection.

Military
    The horizontal plan (XY or YX) is kept at true size and rotated 45
    degrees, so its two axes are at 45 and 135 degrees on screen and still
    90 degrees to each other.  The vertical axis is drawn vertically with
    the reduction factor (0.5 by default).  This is the planometric /
    military convention.

Both families expose a reduction factor for the oblique faces.  The plugin
frames the model after applying a preset and keeps the shear centred on the
model, so the drawing does not drift off screen.

Install: copy this file into the IngeTrazo user plugins folder and restart
IngeTrazo (Extensions > Open plugins folder).
"""

from __future__ import annotations

import logging
import math
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

__version__ = "1.1.0"

log = logging.getLogger("ingetrazo.plugins.oblique_axonometric_cameras")

# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

#: World axes (IngeTrazo is Z-up, metres).
AXES = {
    "X": QVector3D(1.0, 0.0, 0.0),
    "Y": QVector3D(0.0, 1.0, 0.0),
    "Z": QVector3D(0.0, 0.0, 1.0),
}
_AXIS_NAMES = ("X", "Y", "Z")

#: Cabinet plane name -> (horizontal axis, vertical axis) in the view.  The
#: receding axis is the third world axis (``v x h``, into the screen).
PLANES = {
    "XZ": ("X", "Z"),
    "ZX": ("Z", "X"),
    "YZ": ("Y", "Z"),
    "ZY": ("Z", "Y"),
    "XY": ("X", "Y"),
    "YX": ("Y", "X"),
}

PLANE_LABELS = {
    "XZ": "XZ - front (X across, Z up)",
    "ZX": "ZX - side (Z across, X up)",
    "YZ": "YZ - side (Y across, Z up)",
    "ZY": "ZY - side (Z across, Y up)",
    "XY": "XY - plan (rotated 45°)",
    "YX": "YX - plan (rotated 45°, other way)",
}

#: Cabinet: vertical true-size planes and the allowed receding angles.
CABINET_PLANES = ("XZ", "ZX", "YZ", "ZY")
CABINET_ANGLES = (60.0, 45.0, 30.0)

#: Military: horizontal true-size plan, rotated 45 degrees, verticals up.
MILITARY_PLANES = ("XY", "YX")
MILITARY_ROTATION = 45.0
MILITARY_RECEDING_ANGLE = 90.0

DEFAULT_REDUCTION = 0.5
MAX_DISTANCE = 10000.0

RECEDING_SIDES = {
    "right": "Right side",
    "left": "Left side",
}

#: Camera attribute prefix used by the instance patches below.
_MODE_PREFIX = "oblique_axonometric_"


def _make_presets():
    """Build the preset table and its display order."""
    presets = {}
    order = []
    for plane in CABINET_PLANES:
        for angle in CABINET_ANGLES:
            key = f"cabinet_{int(angle)}_{plane.lower()}"
            presets[key] = {
                "label": f"Cabinet {int(angle)}° — {plane}",
                "family": "cabinet",
                "plane": plane,
                "angle_deg": angle,
                "reduction_factor": DEFAULT_REDUCTION,
                "receding_side": "right",
            }
            order.append(key)
    for plane in MILITARY_PLANES:
        key = f"military_{int(MILITARY_ROTATION)}_{plane.lower()}"
        presets[key] = {
            "label": f"Military {int(MILITARY_ROTATION)}° — {plane}",
            "family": "military",
            "plane": plane,
            "angle_deg": MILITARY_ROTATION,
            "reduction_factor": DEFAULT_REDUCTION,
            "receding_side": "right",
        }
        order.append(key)
    return presets, tuple(order)


PRESETS, PRESET_ORDER = _make_presets()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _vec_tuple(vec):
    return (vec.x(), vec.y(), vec.z())


def _axis_slot(vec):
    """(index, sign) of a unit world axis: 0 = X, 1 = Y, 2 = Z."""
    for i, comp in enumerate(_vec_tuple(vec)):
        if abs(comp) > 0.5:
            return i, 1.0 if comp > 0.0 else -1.0
    raise ValueError(f"not a unit axis: {vec!r}")


def _axis_name(vec):
    """'+X', '-Y', ... for a unit world axis."""
    i, sign = _axis_slot(vec)
    return ("+" if sign > 0.0 else "-") + _AXIS_NAMES[i]


def _normalize_plane(plane):
    p = str(plane or "XZ").upper()
    return p if p in PLANES else "XZ"


def _normalize_receding_side(side):
    s = str(side or "right").lower()
    return s if s in RECEDING_SIDES else "right"


def _normalize_family(family):
    return "military" if str(family).lower() == "military" else "cabinet"


def _family_for_plane(plane):
    """Military is the horizontal plan; everything else is Cabinet."""
    return "military" if plane in MILITARY_PLANES else "cabinet"


def _format_factor(value):
    v = float(value)
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.3f}".rstrip("0").rstrip(".")


def _as_vector(value):
    """Accept a QVector3D or a three-number sequence."""
    if isinstance(value, QVector3D):
        return QVector3D(value)
    return QVector3D(float(value[0]), float(value[1]), float(value[2]))


# ---------------------------------------------------------------------------
# Projection axes
# ---------------------------------------------------------------------------

def _cabinet_axes(plane):
    """(screen right, screen up, receding axis) for a Cabinet plane.

    The receding axis points into the screen, away from the viewer, so the
    far side of the model is the side that recedes to the upper right (or
    upper left with the "left" setting).
    """
    h = AXES[PLANES[plane][0]]
    v = AXES[PLANES[plane][1]]
    n = QVector3D.crossProduct(v, h).normalized()   # into the screen
    return h, v, n


def _military_axes(plane, rotation_deg):
    """(screen right, screen up, receding axis) for a Military plan.

    The plan is rotated ``rotation_deg`` on screen, so it stands on its
    corner; its two axes remain 90 degrees apart.  The vertical axis (Z) is
    the receding axis and is drawn vertically.
    """
    x, y = AXES["X"], AXES["Y"]
    if plane == "XY":
        h = (x - y) * (1.0 / math.sqrt(2.0))
        v = (x + y) * (1.0 / math.sqrt(2.0))
    else:  # YX
        h = (x + y) * (1.0 / math.sqrt(2.0))
        v = (y - x) * (1.0 / math.sqrt(2.0))

    # A rotation of the whole plan by ``rotation_deg`` about the view axis.
    t = math.radians(float(rotation_deg) - MILITARY_ROTATION)
    if abs(t) > 1e-12:
        ct, st = math.cos(t), math.sin(t)
        h, v = h * ct - v * st, h * st + v * ct

    n = QVector3D(0.0, 0.0, 1.0)                    # verticals recede upward
    return h.normalized(), v.normalized(), n


def _projection_axes(family, plane, angle_deg):
    if _normalize_family(family) == "military":
        return _military_axes(plane, angle_deg)
    return _cabinet_axes(plane)


def _current_axes(camera):
    plane = _normalize_plane(getattr(camera, "oblique_plane", "XZ"))
    family = _normalize_family(
        getattr(camera, "oblique_family", None) or _family_for_plane(plane)
    )
    angle = float(getattr(camera, "oblique_angle_deg", 45.0))
    return _projection_axes(family, plane, angle)


def _current_receding_angle(camera):
    family = _normalize_family(getattr(camera, "oblique_family", "cabinet"))
    if family == "military":
        return MILITARY_RECEDING_ANGLE
    return float(getattr(camera, "oblique_angle_deg", 45.0))


def _clean_unit(vec):
    """Snap a near-unit vector to the exact axis, to avoid a -0.0 yaw."""
    def clean(comp):
        if abs(comp) < 1e-6:
            return 0.0
        if abs(comp - 1.0) < 1e-6:
            return 1.0
        if abs(comp + 1.0) < 1e-6:
            return -1.0
        return comp

    return QVector3D(clean(vec.x()), clean(vec.y()), clean(vec.z())).normalized()


def _orientation(h, v):
    """(yaw, pitch, up) that puts ``h``/``v`` on the screen."""
    eye_dir = _clean_unit(QVector3D.crossProduct(h, v))
    if abs(eye_dir.x()) < 1e-9 and abs(eye_dir.y()) < 1e-9:
        yaw = 0.0                      # exact top/bottom: yaw is undefined
    else:
        yaw = math.atan2(eye_dir.y(), eye_dir.x())
    pitch = math.asin(max(-1.0, min(1.0, eye_dir.z())))
    return yaw, pitch, v


def _shear_coefficients(angle_deg, factor, side):
    """Screen components of the receding axis: (c, s) in (h, v)."""
    rad = math.radians(float(angle_deg))
    sign = 1.0 if _normalize_receding_side(side) == "right" else -1.0
    return sign * float(factor) * math.cos(rad), sign * float(factor) * math.sin(rad)


def _build_shear(h, v, n, angle_deg, factor, side, pivot=None):
    """Row-major shear that recedes ``n`` into the view.

    The true-size plane spanned by ``h`` and ``v`` is left untouched; only
    the coordinate along the receding axis ``n`` is folded into the screen
    right and up directions by the reduction factor and the drawing angle.
    ``pivot`` keeps the shear centred on the model instead of the world
    origin, so the framing does not drift.
    """
    c, s = _shear_coefficients(angle_deg, factor, side)
    ht, vt, nt = _vec_tuple(h), _vec_tuple(v), _vec_tuple(n)
    data = [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]
    for i in range(3):
        for j in range(3):
            data[i * 4 + j] += (c * ht[i] + s * vt[i]) * nt[j]
    shear = QMatrix4x4(*data)  # type: ignore[arg-type]

    if pivot is None:
        return shear
    centre = _as_vector(pivot)
    m = QMatrix4x4()
    m.translate(centre)
    m = m * shear
    m.translate(-centre)
    return m


def _screen_offset(h, v, n, angle_deg, factor, side, point, pivot):
    """Projected (h, v) coordinates of ``point`` relative to ``pivot``."""
    d = _as_vector(point) - _as_vector(pivot)
    depth = QVector3D.dotProduct(n, d)
    c, s = _shear_coefficients(angle_deg, factor, side)
    return (
        QVector3D.dotProduct(h, d) + c * depth,
        QVector3D.dotProduct(v, d) + s * depth,
    )


# ---------------------------------------------------------------------------
# Camera patch
# ---------------------------------------------------------------------------

def _is_oblique(camera):
    mode = getattr(camera, "oblique_mode", None)
    return isinstance(mode, str) and mode.startswith(_MODE_PREFIX)


def _install_oblique_projection(camera):
    """Monkey-patch a camera instance to produce oblique projections."""
    if getattr(camera, "_oblique_axonometric_patched", False):
        return

    camera._oblique_orig_projection = camera.projection_matrix
    camera._oblique_orig_view = camera.view_matrix
    camera._oblique_orig_mode = camera.projection_mode

    def projection_matrix(_self=camera):
        if not _is_oblique(_self):
            return _self._oblique_orig_projection()
        # An oblique axonometric is a parallel projection: force orthographic
        # for as long as the matrix is built, then restore the camera state.
        prev_perspective = bool(getattr(_self, "perspective", True))
        prev_two_point = bool(getattr(_self, "two_point", False))
        try:
            _self.perspective = False
            _self.two_point = False
            return _self._oblique_orig_projection()
        finally:
            _self.perspective = prev_perspective
            _self.two_point = prev_two_point

    def view_matrix(_self=camera):
        if not _is_oblique(_self):
            return _self._oblique_orig_view()
        try:
            base = _self._oblique_orig_view()
            h, v, n = _current_axes(_self)
            angle = _current_receding_angle(_self)
            factor = float(getattr(_self, "oblique_reduction_factor",
                                   DEFAULT_REDUCTION))
            side = _normalize_receding_side(
                getattr(_self, "oblique_receding_side", "right"))
            pivot = getattr(_self, "oblique_pivot", None)
            if pivot is None:
                pivot = _self.target
            return base * _build_shear(h, v, n, angle, factor, side, pivot)
        except Exception:
            log.exception("Could not apply the oblique shear")
            return _self._oblique_orig_view()

    def projection_mode(_self=camera):
        if _is_oblique(_self):
            return "parallel"
        return _self._oblique_orig_mode()

    camera.projection_matrix = projection_matrix
    camera.view_matrix = view_matrix
    camera.projection_mode = projection_mode
    camera._oblique_axonometric_patched = True


def _deactivate_oblique(camera, notify=True):
    """Drop the oblique state, keeping the current view direction."""
    if not _is_oblique(camera):
        return
    camera.oblique_mode = None
    camera.perspective = False
    camera.two_point = False
    log.debug("Oblique projection cleared")
    if not notify:
        return
    viewport = getattr(camera, "_oblique_viewport", None)
    if viewport is None:
        return
    try:
        viewport.update()
    except Exception:
        pass
    try:
        signal = getattr(viewport, "projectionChanged", None)
        if signal is not None:
            signal.emit(camera.projection_mode())
    except Exception:
        log.exception("Could not notify the projection change")


def _install_rotation_guard(camera):
    """Clear the oblique shear when the user rotates the camera.

    The true-size plane is tied to the chosen preset (XZ, XY, ...).  As soon
    as the user orbits, that plane is no longer the screen plane, so keeping
    the shear would leave a confusing view.  Zooming and panning keep it.
    """
    if getattr(camera, "_oblique_rotation_guard", False):
        return
    for name in (
        "orbit", "orbit_about", "turn", "look_from", "set_view", "snap_iso",
        "set_projection", "toggle_projection", "toggle_two_point",
    ):
        original = getattr(camera, name, None)
        if original is None:
            continue

        def guard(*args, _original=original, _camera=camera, **kwargs):
            _deactivate_oblique(_camera)
            return _original(*args, **kwargs)

        setattr(camera, name, guard)
    camera._oblique_rotation_guard = True


def _fit_oblique_box(camera, min_pt, max_pt, margin=1.12):
    """Frame a box as the current oblique projection draws it."""
    min_pt = _as_vector(min_pt)
    max_pt = _as_vector(max_pt)
    h, v, n = _current_axes(camera)
    angle = _current_receding_angle(camera)
    factor = float(getattr(camera, "oblique_reduction_factor", DEFAULT_REDUCTION))
    side = _normalize_receding_side(
        getattr(camera, "oblique_receding_side", "right"))

    pivot = (min_pt + max_pt) * 0.5
    xs, ys = [], []
    for x in (min_pt.x(), max_pt.x()):
        for y in (min_pt.y(), max_pt.y()):
            for z in (min_pt.z(), max_pt.z()):
                px, py = _screen_offset(
                    h, v, n, angle, factor, side, QVector3D(x, y, z), pivot)
                xs.append(px)
                ys.append(py)

    half_w = (max(xs) - min(xs)) * 0.5
    half_h = (max(ys) - min(ys)) * 0.5
    cx = (max(xs) + min(xs)) * 0.5
    cy = (max(ys) + min(ys)) * 0.5

    camera.oblique_pivot = QVector3D(pivot)
    camera.target = pivot + h * cx + v * cy

    aspect = float(getattr(camera, "aspect", 1.0) or 1.0)
    if not math.isfinite(aspect) or aspect <= 1e-6:
        aspect = 1.0
    fov = float(getattr(camera, "fov_deg", 45.0))
    tan_half = math.tan(math.radians(fov) / 2.0)
    if not math.isfinite(tan_half) or tan_half <= 1e-9:
        tan_half = 1.0
    distance = max(half_h, half_w / aspect) / tan_half * float(margin)
    try:
        floor = float(camera.min_distance(pivot))
    except Exception:
        floor = 0.01
    camera.distance = max(min(distance, MAX_DISTANCE), floor)


def _install_fit_guard(camera):
    """Make Zoom Extents account for the oblique shear."""
    if getattr(camera, "_oblique_fit_guard", False):
        return
    original_fit_box = camera.fit_box
    original_fit_to = camera.fit_to

    def fit_box(min_pt, max_pt, margin=1.1, _camera=camera):
        if not _is_oblique(_camera):
            return original_fit_box(min_pt, max_pt, margin)
        _fit_oblique_box(_camera, min_pt, max_pt, margin)

    def fit_to(min_pt, max_pt, margin=1.3, _camera=camera):
        if not _is_oblique(_camera):
            return original_fit_to(min_pt, max_pt, margin)
        _fit_oblique_box(_camera, min_pt, max_pt, margin)

    camera.fit_box = fit_box
    camera.fit_to = fit_to
    camera._oblique_fit_guard = True


def _ensure_camera_attrs(camera):
    defaults = {
        "oblique_mode": None,
        "oblique_plane": "XZ",
        "oblique_family": "cabinet",
        "oblique_angle_deg": 45.0,
        "oblique_reduction_factor": DEFAULT_REDUCTION,
        "oblique_receding_side": "right",
        "oblique_label": None,
        "oblique_pivot": QVector3D(0.0, 0.0, 0.0),
    }
    for name, value in defaults.items():
        if not hasattr(camera, name):
            setattr(camera, name, value)


def _emit_projection_changed(viewport, camera):
    try:
        signal = getattr(viewport, "projectionChanged", None)
        if signal is not None:
            signal.emit(camera.projection_mode())
    except Exception:
        log.exception("Could not notify the projection change")


def _scene_bounds(viewport):
    try:
        lo, hi = viewport.scene.bounds()
        if lo is None or hi is None:
            return None
        return _as_vector(lo), _as_vector(hi)
    except Exception:
        log.exception("Could not read the scene bounds")
        return None


# ---------------------------------------------------------------------------
# Public operations
# ---------------------------------------------------------------------------

def apply_oblique_settings(viewport, *, plane, angle_deg, reduction_factor,
                           receding_side="right", label=None, family=None,
                           frame=True):
    """Put the viewport's camera in an oblique axonometric projection."""
    try:
        plane = _normalize_plane(plane)
        side = _normalize_receding_side(receding_side)
        family = _normalize_family(
            family if family is not None else _family_for_plane(plane))
        cam = viewport.camera
        _ensure_camera_attrs(cam)
        _install_oblique_projection(cam)
        _install_rotation_guard(cam)
        _install_fit_guard(cam)
        cam._oblique_viewport = viewport

        h, v, _n = _projection_axes(family, plane, float(angle_deg))
        yaw, pitch, up = _orientation(h, v)
        cam.yaw = yaw
        cam.pitch = pitch
        try:
            cam.up = up
        except Exception:
            log.exception("Could not set the camera up vector")

        cam.perspective = False
        cam.two_point = False
        cam.oblique_mode = _MODE_PREFIX + family + "_" + plane.lower()
        cam.oblique_plane = plane
        cam.oblique_family = family
        cam.oblique_angle_deg = float(angle_deg)
        cam.oblique_reduction_factor = float(reduction_factor)
        cam.oblique_receding_side = side
        if label:
            cam.oblique_label = str(label)

        bounds = _scene_bounds(viewport) if frame else None
        if bounds is not None:
            _fit_oblique_box(cam, bounds[0], bounds[1])
        else:
            cam.oblique_pivot = QVector3D(cam.target)

        viewport.update()
        _emit_projection_changed(viewport, cam)
        return True
    except Exception:
        log.exception("Failed to apply the oblique camera")
        return False


def frame_oblique(viewport):
    """Frame the model as the current oblique projection draws it."""
    try:
        cam = viewport.camera
        _ensure_camera_attrs(cam)
        if not _is_oblique(cam):
            return False
        bounds = _scene_bounds(viewport)
        if bounds is None:
            return False
        _fit_oblique_box(cam, bounds[0], bounds[1])
        viewport.update()
        return True
    except Exception:
        log.exception("Failed to frame the oblique view")
        return False


def clear_oblique(viewport):
    """Disable the oblique projection and return to a parallel camera."""
    try:
        cam = viewport.camera
        _ensure_camera_attrs(cam)
        _deactivate_oblique(cam, notify=False)
        cam.perspective = False
        cam.two_point = False
        viewport.update()
        _emit_projection_changed(viewport, cam)
        return True
    except Exception:
        log.exception("Failed to clear the oblique camera")
        return False


def apply_oblique_preset(viewport, preset_key, frame=True):
    """Apply a named oblique camera preset to the active viewport."""
    preset = PRESETS.get(preset_key)
    if preset is None:
        log.warning("Unknown oblique preset: %s", preset_key)
        return False
    return apply_oblique_settings(
        viewport,
        plane=preset["plane"],
        angle_deg=preset["angle_deg"],
        reduction_factor=preset["reduction_factor"],
        receding_side=preset["receding_side"],
        label=preset["label"],
        family=preset["family"],
        frame=frame,
    )


def _describe_settings(plane, angle, factor, side, family):
    h, v, n = _projection_axes(family, plane, angle)
    side_label = RECEDING_SIDES[side].lower()
    if family == "military":
        return (
            f"Military: true-size plan {plane} rotated {angle:g}° "
            f"(plan axes at 90°). Vertical axis {_axis_name(n)} drawn "
            f"vertically at {_format_factor(factor)}x. "
            f"Receding side: {side_label}."
        )
    return (
        f"Cabinet: true-size plane {plane} "
        f"({PLANES[plane][0]} horizontal, {PLANES[plane][1]} vertical). "
        f"Receding axis {_axis_name(n)} at {angle:g}°, "
        f"length {_format_factor(factor)}x. "
        f"Receding side: {side_label}."
    )


def preset_description(preset_key):
    p = PRESETS.get(preset_key) or {}
    plane = _normalize_plane(p.get("plane"))
    angle = float(p.get("angle_deg", 45.0))
    factor = float(p.get("reduction_factor", DEFAULT_REDUCTION))
    side = _normalize_receding_side(p.get("receding_side"))
    family = _normalize_family(p.get("family") or _family_for_plane(plane))
    return _describe_settings(plane, angle, factor, side, family)


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class ObliqueAxonometricPanel(QWidget):
    """Panel for the Cabinet and Military oblique camera presets."""

    def __init__(self, app):
        super().__init__()
        self._app = app
        self._updating = False
        self._last_family = "cabinet"
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        intro = QLabel(
            "<b>Oblique axonometric cameras.</b> "
            "<b>Cabinet</b> keeps a vertical plane (XZ, ZX, YZ, ZY) at true "
            "size, its axes horizontal and vertical, and recedes the "
            "complementary axis at 30°, 45° or 60°. "
            "<b>Military</b> keeps the horizontal plan (XY, YX) at true size, "
            "rotated 45° so its axes stay at 90°, and draws the "
            "vertical axis vertically. The reduction factor foreshortens the "
            "oblique faces (0.5 = Cabinet; 1.0 = Cavalier)."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFormAlignment(Qt.AlignTop)

        self._preset = QComboBox()
        for key in PRESET_ORDER:
            self._preset.addItem(PRESETS[key]["label"], key)
        self._preset.currentIndexChanged.connect(self._on_preset_changed)
        form.addRow("Preset:", self._preset)

        self._plane = QComboBox()
        for key in ("XZ", "ZX", "YZ", "ZY", "XY", "YX"):
            self._plane.addItem(PLANE_LABELS[key], key)
        self._plane.currentIndexChanged.connect(self._on_plane_changed)
        form.addRow("True-size plane:", self._plane)

        self._angle = QDoubleSpinBox()
        self._angle.setRange(0.0, 90.0)
        self._angle.setDecimals(1)
        self._angle.setSingleStep(1.0)
        self._angle.setSuffix(" °")
        self._angle.valueChanged.connect(self._on_settings_changed)
        form.addRow("Angle (Cabinet: receding, Military: plan rotation):",
                    self._angle)

        self._reduction = QDoubleSpinBox()
        self._reduction.setRange(0.0, 2.0)
        self._reduction.setDecimals(3)
        self._reduction.setSingleStep(0.05)
        self._reduction.setValue(DEFAULT_REDUCTION)
        self._reduction.valueChanged.connect(self._on_settings_changed)
        form.addRow("Reduction factor (oblique faces):", self._reduction)

        self._side = QComboBox()
        for key in ("right", "left"):
            self._side.addItem(RECEDING_SIDES[key], key)
        self._side.currentIndexChanged.connect(self._on_settings_changed)
        form.addRow("Receding side:", self._side)

        self._frame = QCheckBox("Frame the model after applying")
        self._frame.setChecked(True)
        form.addRow("", self._frame)

        self._details = QLabel("")
        self._details.setWordWrap(True)
        form.addRow("Details:", self._details)

        root.addLayout(form)

        actions = QHBoxLayout()
        self._apply_preset_btn = QPushButton("Apply preset")
        self._apply_preset_btn.clicked.connect(self._apply_selected_preset)
        self._apply_custom_btn = QPushButton("Apply settings")
        self._apply_custom_btn.clicked.connect(self._apply_custom_settings)
        self._frame_btn = QPushButton("Frame model")
        self._frame_btn.clicked.connect(self._frame_model)
        self._clear_btn = QPushButton("Clear oblique")
        self._clear_btn.clicked.connect(self._clear)
        actions.addWidget(self._apply_preset_btn)
        actions.addWidget(self._apply_custom_btn)
        actions.addWidget(self._frame_btn)
        actions.addWidget(self._clear_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)
        root.addStretch(1)

        self._on_preset_changed()

    # ---- state ------------------------------------------------------------
    def _selected_preset_key(self):
        key = self._preset.currentData()
        return str(key) if key else None

    def _selected_plane(self):
        key = self._plane.currentData()
        return _normalize_plane(str(key) if key else "XZ")

    def _selected_side(self):
        key = self._side.currentData()
        return _normalize_receding_side(str(key) if key else "right")

    def _sync_details(self):
        plane = self._selected_plane()
        family = _family_for_plane(plane)
        angle = float(self._angle.value())
        factor = float(self._reduction.value())
        side = self._selected_side()
        note = ""
        if abs(factor - 1.0) < 1e-9:
            note = ("\nA reduction factor of 1.0 is a Cavalier projection "
                    "(no foreshortening).")
        self._details.setText(
            _describe_settings(plane, angle, factor, side, family) + note)

    # ---- handlers ---------------------------------------------------------
    def _on_preset_changed(self, _index=0):
        key = self._selected_preset_key()
        preset = PRESETS.get(key or "")
        if not preset:
            self._sync_details()
            return
        self._updating = True
        try:
            plane = _normalize_plane(preset.get("plane", "XZ"))
            idx = self._plane.findData(plane)
            if idx >= 0:
                self._plane.setCurrentIndex(idx)
            side = _normalize_receding_side(preset.get("receding_side", "right"))
            sidx = self._side.findData(side)
            if sidx >= 0:
                self._side.setCurrentIndex(sidx)
            self._angle.setValue(float(preset.get("angle_deg", 45.0)))
            self._reduction.setValue(
                float(preset.get("reduction_factor", DEFAULT_REDUCTION)))
            self._last_family = _family_for_plane(plane)
        finally:
            self._updating = False
        self._sync_details()

    def _on_plane_changed(self, _index=0):
        if self._updating:
            return
        family = _family_for_plane(self._selected_plane())
        if family == "military" and self._last_family != "military":
            # The standard Military drawing is rotated 45 degrees.
            self._updating = True
            try:
                self._angle.setValue(MILITARY_ROTATION)
            finally:
                self._updating = False
        self._last_family = family
        self._sync_details()

    def _on_settings_changed(self, *_args):
        if self._updating:
            return
        self._sync_details()

    def _viewport_or_status(self):
        try:
            return self._app.viewport
        except Exception:
            self._status.setText("No active viewport is available.")
            return None

    # ---- actions ----------------------------------------------------------
    def _apply_selected_preset(self):
        key = self._selected_preset_key()
        if not key:
            self._status.setText("Select a preset.")
            return
        vp = self._viewport_or_status()
        if vp is None:
            return
        if apply_oblique_preset(vp, key, frame=self._frame.isChecked()):
            self._status.setText(
                f"Applied {PRESETS[key]['label']}. {preset_description(key)}")
        else:
            self._status.setText(
                "Could not apply the selected preset. Check the log.")

    def _apply_custom_settings(self):
        vp = self._viewport_or_status()
        if vp is None:
            return
        plane = self._selected_plane()
        angle = float(self._angle.value())
        factor = float(self._reduction.value())
        side = self._selected_side()
        family = _family_for_plane(plane)
        label = f"Custom {family.capitalize()} - {plane}"
        if apply_oblique_settings(
            vp, plane=plane, angle_deg=angle, reduction_factor=factor,
            receding_side=side, label=label, family=family,
            frame=self._frame.isChecked(),
        ):
            self._status.setText(
                f"Applied {label}. "
                f"{_describe_settings(plane, angle, factor, side, family)}")
        else:
            self._status.setText(
                "Could not apply the custom settings. Check the log.")

    def _frame_model(self):
        vp = self._viewport_or_status()
        if vp is None:
            return
        if frame_oblique(vp):
            self._status.setText("Framed the model in the oblique view.")
        else:
            self._status.setText("Could not frame the model.")

    def _clear(self):
        vp = self._viewport_or_status()
        if vp is None:
            return
        if clear_oblique(vp):
            self._status.setText("Oblique projection cleared.")
        else:
            self._status.setText("Could not clear the oblique projection.")


# ---------------------------------------------------------------------------
# Extension entry point
# ---------------------------------------------------------------------------

def setup(app):
    """Register the oblique camera panel and menu actions."""
    panel = ObliqueAxonometricPanel(app)
    dock = None
    try:
        dock = app.add_panel(
            "Oblique Axonometric Cameras", panel, name="oblique_axonometric")
    except Exception:
        log.exception("Could not create the Oblique Axonometric Cameras panel")

    def show_panel():
        if dock is None:
            return
        try:
            app.show_panel(dock)
        except Exception:
            try:
                dock.show()
                dock.raise_()
            except Exception:
                log.exception("Could not show the Oblique Axonometric Cameras panel")

    def apply(key):
        try:
            vp = app.viewport
        except Exception:
            log.exception("No viewport available for oblique preset: %s", key)
            return
        if apply_oblique_preset(vp, key):
            label = PRESETS.get(key, {}).get("label", key)
            try:
                vp.flash_status(
                    f"Oblique camera: {label} - {preset_description(key)}",
                    3500)
            except Exception:
                pass

    def frame():
        try:
            vp = app.viewport
        except Exception:
            return
        if frame_oblique(vp):
            try:
                vp.flash_status("Oblique view framed on the model.", 2500)
            except Exception:
                pass

    try:
        menu = app.add_menu("Oblique Axonometric Cameras")
        for key in PRESET_ORDER:
            label = PRESETS[key]["label"]
            tip = preset_description(key)
            action = menu.addAction(label, partial(apply, key))
            action.setStatusTip(tip)
        menu.addSeparator()
        menu.addAction("Frame model", frame).setStatusTip(
            "Frame the model as the current oblique projection draws it.")
        menu.addAction(
            "Open Oblique Axonometric Cameras panel...", show_panel
        ).setStatusTip(
            "Open the panel to choose a plane, angle and reduction factor.")
        menu.addAction(
            "Clear oblique projection", lambda: clear_oblique(app.viewport)
        ).setStatusTip("Return to a standard parallel projection.")
    except Exception:
        log.exception("Could not create the Oblique Axonometric Cameras menu")
        try:
            app.add_menu_action(
                "Oblique Axonometric Cameras...", show_panel,
                tip="Apply Cabinet and Military oblique camera presets.")
        except Exception:
            log.exception("Could not register the fallback oblique camera action")

    log.info(
        "Oblique Axonometric Cameras extension loaded (key=%s)",
        getattr(app, "key", "?"))
