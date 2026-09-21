"""Draws one ViewFrame into a pygame surface. Pure drawing: no event loop, no clock, no I/O.

Layout (1280 x 720):  left, the lunar scene (LM mesh, grid, target, hazards, trail, plume) over the
descent profile and the radar-vs-AGC altitude strip; right, the AGC/DSKY, telemetry, the policy's
latest decision and a legend saying what is real data and what is drawing.

**Real data** (from the plant, the AGC and the log): position, altitude, velocities, mass, thrust,
pitch, DSKY, alarms, radar/AGC altitudes, intents, vetoes, the target and the seeded hazards.
**Cosmetic**: the LM mesh detail (NASA model, simplified), the plume, the ground tint and the grid.
The contact plane is altitude 0; relief is shown only as a tint of the grid lines by local slope.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pygame
from numpy.typing import NDArray

from luminary_agent.lem.mesh import LemMesh, load_lem_mesh
from luminary_agent.plant.terrain import CLEAR_RADIUS_M, TARGET_RADIUS_M, Surface
from luminary_agent.viz.view_model import ViewFrame

SIZE = (1280, 720)
SCENE = pygame.Rect(0, 0, 800, 470)
PROFILE = pygame.Rect(0, 470, 470, 250)
STRIP = pygame.Rect(470, 470, 330, 250)
PANEL_X = 800

BG = (10, 11, 13)
PANEL_BG = (16, 17, 20)
LINE = (52, 54, 58)
GRID = (74, 77, 82)
GROUND = (27, 28, 31)  # the lunar surface: dark grey, just enough to be seen against the black sky
HORIZON = (58, 60, 64)
TEXT = (208, 212, 208)
DIM = (122, 127, 122)
CAUTION = (232, 172, 44)
ALARM = (238, 72, 62)
DSKY = (112, 236, 140)

CAMERAS = {1: "chase", 2: "ground", 3: "top"}
SPRITE_PX_PER_M = 30.0
CAMERA_DIST_M = 32.0  # chase and top cameras keep this distance from the LM, at any altitude
SPRITE_CACHE = 160
NEAR = 0.5
LEM_BELL = np.array([0.0, 0.0, 0.45])  # engine exit, mesh frame
LEM_LIGHT = np.array([-0.4, 0.7, 0.6]) / np.linalg.norm([-0.4, 0.7, 0.6])
NICE = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000)


@dataclass(frozen=True)
class Camera:
    eye: NDArray[np.float64]
    right: NDArray[np.float64]
    up: NDArray[np.float64]
    fwd: NDArray[np.float64]
    focal: float
    cx: float
    cy: float

    @classmethod
    def look_at(
        cls, eye: NDArray[np.float64], target: NDArray[np.float64], rect: pygame.Rect,
        up_hint: tuple[float, float, float] = (0.0, 1.0, 0.0), fov_deg: float = 50.0,
    ) -> Camera:  # fmt: skip
        fwd = target - eye
        fwd = fwd / np.linalg.norm(fwd)
        right = np.cross(fwd, np.array(up_hint))
        right = right / np.linalg.norm(right)
        focal = rect.w / 2 / math.tan(math.radians(fov_deg) / 2)
        return cls(eye, right, np.cross(right, fwd), fwd, focal, rect.centerx, rect.centery)

    def to_cam(self, p: NDArray[np.float64]) -> NDArray[np.float64]:
        d = p - self.eye
        return np.stack([d @ self.right, d @ self.up, d @ self.fwd], axis=-1)

    def screen(self, c: NDArray[np.float64]) -> NDArray[np.float64]:
        z = np.maximum(c[..., 2], 1e-6)
        return np.stack(
            [self.cx + self.focal * c[..., 0] / z, self.cy - self.focal * c[..., 1] / z], -1
        )

    def segments(
        self, a: NDArray[np.float64], b: NDArray[np.float64]
    ) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], NDArray[np.bool_]]:
        """World segments a->b clipped at the near plane: screen ends, mean depth, and the mask
        of the input segments that survived (some are wholly behind the camera)."""
        ca, cb = self.to_cam(a), self.to_cam(b)
        za, zb = ca[:, 2], cb[:, 2]
        keep = (za > NEAR) | (zb > NEAR)
        ca, cb, za, zb = ca[keep], cb[keep], za[keep], zb[keep]
        span = np.where(zb == za, 1e-9, zb - za)
        new_a = np.where((za < NEAR)[:, None], ca + (cb - ca) * ((NEAR - za) / span)[:, None], ca)
        new_b = np.where((zb < NEAR)[:, None], cb + (ca - cb) * ((NEAR - zb) / -span)[:, None], cb)
        return self.screen(new_a), self.screen(new_b), (new_a[:, 2] + new_b[:, 2]) / 2, keep


def _line(
    screen: pygame.Surface,
    color: tuple[int, int, int],
    p: NDArray[np.float64],
    q: NDArray[np.float64],
) -> None:
    """A line clipped to the surface first: segments cut at the near plane can end millions of
    pixels away, and pygame walks the whole unclipped length (3 ms a line)."""
    clipped = screen.get_rect().clipline(float(p[0]), float(p[1]), float(q[0]), float(q[1]))
    if clipped:
        pygame.draw.line(screen, color, clipped[0], clipped[1], 1)


def _nice(x: float) -> float:
    return next((n for n in NICE if n >= x), NICE[-1])


def _rot_z(deg: float) -> NDArray[np.float64]:
    a = math.radians(deg)
    return np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])


# mesh (x forward, y left, z up) -> world (X right/downrange, Y up, Z toward the viewer)
MESH_TO_WORLD = np.array([[1.0, 0, 0], [0, 0, 1.0], [0, -1.0, 0]])


class NativeRenderer:
    def __init__(self, surface: Surface | None = None) -> None:
        pygame.font.init()

        def font(size: int, bold: bool = False) -> pygame.font.Font:
            return pygame.font.SysFont("menlo,monaco,couriernew,courier", size, bold=bold)

        self.f_small, self.f_med, self.f_big, self.f_dsky = (
            font(12),
            font(14),
            font(17, True),
            font(30, True),
        )
        self.terrain = surface
        self.mesh: LemMesh = load_lem_mesh()
        self.slopes = surface.slope_map(2500.0, 25.0) if surface else None
        self._sprites: OrderedDict[tuple[int, int, int], tuple[pygame.Surface, tuple[int, int]]] = (
            OrderedDict()
        )
        self.sprite_misses = 0

    # --- the LM ------------------------------------------------------------------------------

    def _sprite(self, pitch_deg: float, cam: Camera) -> tuple[pygame.Surface, tuple[int, int]]:
        """The LM seen from `cam`'s direction at this pitch, drawn once and cached: an orthographic
        picture at SPRITE_PX_PER_M, plus the pixel of the mesh origin."""
        d = cam.fwd
        yaw, elev = (
            round(math.degrees(math.atan2(d[2], d[0])) / 2),
            round(math.degrees(math.asin(d[1])) / 2),
        )
        key = (round(pitch_deg / 2), yaw, elev)
        hit = self._sprites.get(key)
        if hit is not None:
            self._sprites.move_to_end(key)
            return hit
        self.sprite_misses += 1
        el, ya = math.radians(elev * 2), math.radians(yaw * 2)
        fwd = np.array([math.cos(el) * math.cos(ya), math.sin(el), math.cos(el) * math.sin(ya)])
        right = np.cross(fwd, (0, 1, 0)) if abs(fwd[1]) < 0.999 else np.array([1.0, 0, 0])
        right = right / np.linalg.norm(right)
        up = np.cross(right, fwd)
        world = (_rot_z(key[0] * 2) @ MESH_TO_WORLD @ self.mesh.vertices.astype(float).T).T
        cam_xyz = np.stack([world @ right, world @ up, world @ fwd], axis=1)
        half = 240
        surf = pygame.Surface((2 * half, 2 * half), pygame.SRCALPHA)
        px = np.stack(
            [half + cam_xyz[:, 0] * SPRITE_PX_PER_M, half - cam_xyz[:, 1] * SPRITE_PX_PER_M], 1
        )
        tri = cam_xyz[self.mesh.faces]
        normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        normal /= np.linalg.norm(normal, axis=1)[:, None] + 1e-12
        wn = normal[:, 0:1] * right + normal[:, 1:2] * up + normal[:, 2:3] * fwd  # to world
        shade = 0.4 + 0.6 * np.abs(wn @ LEM_LIGHT)
        colors = np.clip(self.mesh.colors * shade[:, None], 0, 255).astype(int)
        for i in np.argsort(-tri[:, :, 2].mean(1)):  # far to near
            pygame.draw.polygon(surf, tuple(colors[i]), px[self.mesh.faces[i]].tolist())
        entry = (surf, (half, half))
        self._sprites[key] = entry
        if len(self._sprites) > SPRITE_CACHE:
            self._sprites.popitem(last=False)
        return entry

    def _draw_lem(self, screen: pygame.Surface, cam: Camera, f: ViewFrame) -> None:
        pos = np.array([f.downrange_m, f.h_m, f.cross_m])
        c = cam.to_cam(pos[None])[0]
        if c[2] < NEAR:
            return
        sx, sy = cam.screen(c[None])[0]
        px_per_m = cam.focal / c[2]
        if (
            f.thrust_n > 0 and f.h_m > 0.5
        ):  # plume: cosmetic, length and width follow the real throttle
            self._draw_plume(screen, cam, pos, f)
        if px_per_m * 7.0 < 6:  # too far to draw a vehicle: a marker
            pygame.draw.circle(screen, CAUTION, (int(sx), int(sy)), 3)
            return
        sprite, (ox, oy) = self._sprite(f.pitch_deg, cam)
        k = px_per_m / SPRITE_PX_PER_M
        size = (max(1, int(sprite.get_width() * k)), max(1, int(sprite.get_height() * k)))
        img = (
            pygame.transform.smoothscale(sprite, size)
            if k < 1.0
            else pygame.transform.scale(sprite, size)
        )
        screen.blit(img, (sx - ox * k, sy - oy * k))

    def _draw_plume(
        self, screen: pygame.Surface, cam: Camera, pos: NDArray[np.float64], f: ViewFrame
    ) -> None:
        rot = _rot_z(f.pitch_deg)
        up = rot @ np.array([0.0, 1.0, 0.0])
        side = rot @ np.array([1.0, 0.0, 0.0])
        base = pos + rot @ np.array([0.0, LEM_BELL[2], 0.0])
        length = 2.0 + 14.0 * f.throttle
        for width, tip_scale, color in (
            (1.5, 1.0, (255, 150, 50, 120)),
            (0.7, 0.7, (255, 235, 190, 190)),
        ):
            pts = np.array(
                [base + side * width / 2, base - side * width / 2, base - up * length * tip_scale]
            )
            c = cam.to_cam(pts)
            if (c[:, 2] < NEAR).any():
                continue
            layer = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            pygame.draw.polygon(layer, color, cam.screen(c).tolist())
            screen.blit(layer, (0, 0))

    # --- the ground ---------------------------------------------------------------------------

    def _tint(self, x: NDArray[np.float64], z: NDArray[np.float64]) -> NDArray[np.float64]:
        if self.slopes is None:
            return np.zeros_like(x)
        n = self.slopes.shape[0]
        i = np.clip(np.round((x + 2500.0) / 25.0).astype(int), 0, n - 1)
        j = np.clip(np.round((z + 2500.0) / 25.0).astype(int), 0, n - 1)
        inside = (np.abs(x) <= 2500.0) & (np.abs(z) <= 2500.0)
        return np.where(inside, self.slopes[j, i], 0.0)

    def _draw_ground(self, screen: pygame.Surface, cam: Camera) -> None:
        """Fill the part of the screen that looks at the surface (the plane y = 0). A pixel does
        when its ray points down: g(x, y) < 0, a half-plane of the screen, so it is the screen
        rectangle clipped by one line. That keeps the surface visible from any altitude."""

        def g(pt: tuple[float, float]) -> float:
            return float(
                cam.right[1] * (pt[0] - cam.cx) / cam.focal
                - cam.up[1] * (pt[1] - cam.cy) / cam.focal
                + cam.fwd[1]
            )

        w, h = screen.get_size()
        rect = [(0.0, 0.0), (float(w), 0.0), (float(w), float(h)), (0.0, float(h))]
        ground: list[tuple[float, float]] = []
        for a, b in zip(rect, rect[1:] + rect[:1], strict=True):
            ga, gb = g(a), g(b)
            if ga < 0:
                ground.append(a)
            if (ga < 0) != (gb < 0):
                t = ga / (ga - gb)
                ground.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
        if len(ground) > 2:
            pygame.draw.polygon(screen, GROUND, ground)
            for a, b in zip(ground, ground[1:] + ground[:1], strict=True):
                if 0 < a[0] < w and 0 < b[0] < w and abs(a[1] - b[1]) < 1.5 and 0 < a[1] < h:
                    pygame.draw.line(screen, HORIZON, a, b, 1)  # the horizon

    def _draw_grid(
        self, screen: pygame.Surface, cam: Camera, centre: NDArray[np.float64], dist: float
    ) -> None:
        step = _nice(dist / 4)
        reach = 8 * step
        x0, z0 = round(centre[0] / step) * step, round(centre[2] / step) * step
        ks = np.arange(-8, 9) * step
        chunks = np.arange(-8, 8) * step
        starts: list[tuple[float, float, float]] = []
        ends: list[tuple[float, float, float]] = []
        for k in ks:  # lines of constant z, cut in `step` chunks so each can carry its own tint
            starts += [(x0 + c, 0.0, z0 + k) for c in chunks]
            ends += [(x0 + c + step, 0.0, z0 + k) for c in chunks]
            starts += [(x0 + k, 0.0, z0 + c) for c in chunks]
            ends += [(x0 + k, 0.0, z0 + c + step) for c in chunks]
        a, b = np.array(starts), np.array(ends)
        mid = (a + b) / 2
        slope = self._tint(mid[:, 0], mid[:, 2])
        s0, s1, depth, keep = cam.segments(a, b)
        slope = slope[keep]
        fade = np.clip(depth / (reach * 1.6), 0, 1)
        for p, q, s, fd in zip(s0, s1, slope, fade, strict=True):
            base = ALARM if s >= 12 else CAUTION if s >= 6 else GRID
            red, green, blue = (int(base[i] * (1 - fd) + GROUND[i] * fd) for i in range(3))
            _line(screen, (red, green, blue), p, q)

    def _ring(
        self,
        screen: pygame.Surface,
        cam: Camera,
        cx: float,
        cz: float,
        r: float,
        color: tuple[int, int, int],
    ) -> None:
        t = np.linspace(0, 2 * math.pi, 49)
        pts = np.stack([cx + r * np.cos(t), np.zeros_like(t), cz + r * np.sin(t)], 1)
        s0, s1, _, _ = cam.segments(pts[:-1], pts[1:])
        for p, q in zip(s0, s1, strict=True):
            _line(screen, color, p, q)

    def _draw_surface(
        self, screen: pygame.Surface, cam: Camera, centre: NDArray[np.float64], dist: float
    ) -> None:
        self._draw_grid(screen, cam, centre, dist)
        self._ring(screen, cam, 0, 0, TARGET_RADIUS_M, TEXT)  # the mission-success circle
        self._ring(screen, cam, 0, 0, CLEAR_RADIUS_M, DIM)
        if self.terrain is not None:
            for h in self.terrain.hazards:
                if (
                    math.hypot(h.x_m - centre[0], h.z_m - centre[2])
                    < 9 * _nice(dist / 4) + h.radius_m
                ):
                    self._ring(
                        screen,
                        cam,
                        h.x_m,
                        h.z_m,
                        h.radius_m,
                        ALARM if h.kind == "crater" else CAUTION,
                    )

    def _camera(self, which: int, f: ViewFrame, rect: pygame.Rect) -> tuple[Camera, float]:
        pos = np.array([f.downrange_m, f.h_m, f.cross_m])
        dist = CAMERA_DIST_M
        focus = pos + np.array([0.0, 3.5, 0.0])
        if which == 2:  # a fixed observer beside the target
            eye = np.array([-70.0, 10.0, -110.0])
            return Camera.look_at(eye, focus, rect), float(np.linalg.norm(pos - eye)) / 2
        if which == 3:  # straight down, downrange to the right
            return Camera.look_at(
                pos + np.array([0.0, dist * 1.6, 0.0]), pos, rect, (0.0, 0.0, -1.0)
            ), dist
        az = math.radians(30)
        eye = focus + dist * np.array(
            [-math.cos(az) * math.cos(0.15), math.sin(0.15), math.sin(az) * math.cos(0.15)]
        )
        return Camera.look_at(eye, focus, rect), dist

    def _draw_target_marker(self, screen: pygame.Surface, cam: Camera) -> None:
        """A marker that stays visible when the rings are too small to see."""
        c = cam.to_cam(np.zeros((1, 3)))[0]
        if c[2] < NEAR:
            return
        x, y = (int(v) for v in cam.screen(c[None])[0])
        pygame.draw.polygon(screen, TEXT, [(x, y - 9), (x + 6, y), (x, y + 9), (x - 6, y)], 1)
        screen.blit(self.f_small.render("TARGET", True, TEXT), (x + 10, y - 6))

    def _draw_trail(self, screen: pygame.Surface, cam: Camera, history: list[ViewFrame]) -> None:
        if len(history) < 2:
            return
        step = max(1, len(history) // 500)
        sampled = history[::step] + [history[-1]]
        pts = np.array([[g.downrange_m, g.h_m, g.cross_m] for g in sampled])
        s0, s1, _, _ = cam.segments(pts[:-1], pts[1:])
        for p, q in zip(s0, s1, strict=True):
            _line(screen, CAUTION, p, q)

    def _draw_scene(self, screen: pygame.Surface, history: list[ViewFrame], camera: int) -> None:
        f = history[-1]
        view = screen.subsurface(SCENE)
        view.fill(BG)
        cam, dist = self._camera(camera, f, pygame.Rect(0, 0, SCENE.w, SCENE.h))
        centre = np.array([f.downrange_m, 0.0, f.cross_m])
        self._draw_ground(view, cam)
        self._draw_surface(view, cam, centre, max(dist, float(cam.eye[1])))
        self._draw_trail(view, cam, history)
        self._draw_target_marker(view, cam)
        self._draw_lem(view, cam, f)
        tag = f"{CAMERAS[camera].upper()} CAMERA   TARGET {f.target_error_m:,.0f} m".replace(
            ",", " "
        )
        view.blit(self.f_med.render(tag, True, DIM), (12, 10))
        view.blit(
            self.f_small.render(
                "grid tint: slope >= 6 deg amber, >= 12 deg red;  rings: target 30 m / 100 m",
                True,
                DIM,
            ),
            (12, SCENE.h - 20),
        )

    # --- plots --------------------------------------------------------------------------------

    def _plot_frame(self, screen: pygame.Surface, rect: pygame.Rect, title: str) -> pygame.Rect:
        pygame.draw.rect(screen, PANEL_BG, rect)
        pygame.draw.rect(screen, LINE, rect, 1)
        screen.blit(self.f_med.render(title, True, DIM), (rect.x + 10, rect.y + 6))
        return pygame.Rect(rect.x + 44, rect.y + 28, rect.w - 60, rect.h - 52)

    def _draw_profile(self, screen: pygame.Surface, everything: list[ViewFrame], upto: int) -> None:
        area = self._plot_frame(
            screen, PROFILE, "DESCENT PROFILE  (km: downrange to target / altitude)"
        )
        xs = np.array([g.downrange_m for g in everything]) / 1000.0
        hs = np.array([g.h_m for g in everything]) / 1000.0
        x_lo, x_hi = min(xs.min(), -1.0), 1.0
        h_hi = max(hs.max() * 1.1, 1.0)

        def pt(x: float, h: float) -> tuple[int, int]:
            return (
                int(area.x + (x - x_lo) / (x_hi - x_lo) * area.w),
                int(area.bottom - h / h_hi * area.h),
            )

        pygame.draw.line(screen, LINE, (area.x, area.bottom), (area.right, area.bottom))
        step = max(1, len(xs) // 400)
        line = [pt(x, h) for x, h in zip(xs[::step], hs[::step], strict=True)]
        if len(line) > 1:
            pygame.draw.lines(screen, DIM, False, line, 1)
        done = [pt(x, h) for x, h in zip(xs[: upto + 1 : step], hs[: upto + 1 : step], strict=True)]
        if len(done) > 1:
            pygame.draw.lines(screen, TEXT, False, done, 2)
        tx, ty = pt(0.0, 0.0)
        pygame.draw.circle(screen, TEXT, (tx, ty), 5, 1)
        cx, cy = pt(xs[upto], hs[upto])
        pygame.draw.circle(screen, CAUTION, (cx, cy), 4)
        screen.blit(self.f_small.render(f"{h_hi:.0f}", True, DIM), (PROFILE.x + 8, area.y))
        screen.blit(self.f_small.render("0", True, DIM), (PROFILE.x + 8, area.bottom - 12))
        screen.blit(self.f_small.render(f"{x_lo:.0f} km", True, DIM), (area.x, area.bottom + 4))
        screen.blit(self.f_small.render("target", True, DIM), (tx - 24, ty + 6))

    def _draw_strip(self, screen: pygame.Surface, everything: list[ViewFrame], upto: int) -> None:
        area = self._plot_frame(screen, STRIP, "ALTITUDE  last 200 s")
        f = everything[upto]
        window = [g for g in everything[: upto + 1] if g.t_s >= f.t_s - 200.0]
        top = max(max(g.h_m for g in window), 50.0) * 1.1
        t0 = f.t_s - 200.0

        def y(v: float) -> int:
            return int(area.bottom - min(max(v, 0.0), top) / top * area.h)

        pygame.draw.line(screen, LINE, (area.x, area.bottom), (area.right, area.bottom))
        series: tuple[tuple[tuple[int, int, int], Callable[[ViewFrame], float | None]], ...] = (
            (DIM, lambda g: g.h_m),
            (TEXT, lambda g: g.radar_alt_m),
            (CAUTION, lambda g: g.agc_alt_m),
        )
        for color, get in series:
            pts = [
                (int(area.x + (g.t_s - t0) / 200.0 * area.w), y(v))
                for g in window
                if (v := get(g)) is not None
            ]
            if len(pts) > 1:
                pygame.draw.lines(screen, color, False, pts, 1)
        for n, (name, color) in enumerate((("true", DIM), ("radar", TEXT), ("AGC", CAUTION))):
            screen.blit(self.f_small.render(name, True, color), (area.x + 6 + 56 * n, area.y + 2))
        screen.blit(self.f_small.render(f"{top:.0f} m", True, DIM), (STRIP.x + 4, area.y))

    # --- right panel --------------------------------------------------------------------------

    def _text(
        self,
        screen: pygame.Surface,
        font: pygame.font.Font,
        text: str,
        color: tuple[int, int, int],
        pos: tuple[int, int],
    ) -> None:
        screen.blit(font.render(text, True, color), pos)

    def _draw_panel(
        self, screen: pygame.Surface, f: ViewFrame, status: str, verdict: str | None
    ) -> None:
        panel = pygame.Rect(PANEL_X, 0, SIZE[0] - PANEL_X, SIZE[1])
        pygame.draw.rect(screen, PANEL_BG, panel)
        pygame.draw.line(screen, LINE, (PANEL_X, 0), (PANEL_X, SIZE[1]))
        x = PANEL_X + 16

        def num(v: int | None, width: int = 6) -> str:
            return " " * width if v is None else f"{v:+0{width}d}"[:width]

        self._text(screen, self.f_med, "AGC / DSKY", DIM, (x, 8))
        prog = "--" if f.prog is None else f"{f.prog:02d}"
        verb = 0 if f.verb is None else f.verb
        noun = 0 if f.noun is None else f.noun
        self._text(
            screen,
            self.f_dsky,
            f"PROG {prog}   V {verb:02d}   N {noun:02d}",
            DSKY,
            (x, 28),
        )
        for n, v in enumerate((f.r1, f.r2, f.r3)):
            self._text(screen, self.f_dsky, f"R{n + 1}  {num(v, 7)}", DSKY, (x, 66 + 34 * n))
        lamps = (
            ("ENGINE", f.engine_on, TEXT),
            ("MANUAL", f.mode == "manual", CAUTION),
            ("ALARM", bool(f.alarms), ALARM),
        )
        for n, (name, on, color) in enumerate(lamps):
            box = pygame.Rect(x + 150 * n, 172, 130, 22)
            pygame.draw.rect(screen, color if on else LINE, box, 0 if on else 1)
            self._text(screen, self.f_med, name, BG if on else DIM, (box.x + 10, box.y + 3))

        y = 210
        rows = [
            ("TIME", f"{f.t_s:8.1f} s"),
            ("ALTITUDE", f"{f.h_m:8.1f} m"),
            ("V/S", f"{f.vz_ms:+8.2f} m/s"),
            ("H VEL", f"{f.vh_ms:+8.2f} m/s"),
            ("THRUST", f"{f.thrust_n:8.0f} N {f.throttle * 100:3.0f}%"),
            ("FUEL", f"{f.fuel_kg:8.0f} kg"),
            ("TARGET ERR", f"{f.target_error_m:8.0f} m"),
            ("DOWN/CROSS", f"{f.downrange_m:+7.0f} {f.cross_m:+6.0f} m"),
            ("RADAR ALT", "  no lock" if f.radar_alt_m is None else f"{f.radar_alt_m:8.1f} m"),
            ("AGC ALT", "        -" if f.agc_alt_m is None else f"{f.agc_alt_m:8.1f} m"),
        ]  # fmt: skip
        for label, value in rows:
            self._text(screen, self.f_med, label, DIM, (x, y))
            self._text(screen, self.f_med, value, TEXT, (x + 130, y))
            y += 21
        alarms = " ".join(f"{a:o}" for a in f.alarms) or "none"
        self._text(screen, self.f_med, "ALARMS", DIM, (x, y))
        self._text(screen, self.f_med, alarms, ALARM if f.alarms else TEXT, (x + 130, y))

        y = 452
        pygame.draw.line(screen, LINE, (PANEL_X, y - 8), (SIZE[0], y - 8))
        self._text(
            screen,
            self.f_med,
            f"POLICY  mode {f.mode.upper()}   decisions {f.decisions}   vetoes {f.vetoes}",
            DIM,
            (x, y),
        )
        intent = f.intent or "-"
        font = self.f_big if len(intent) <= 36 else self.f_med  # long intents shrink, not clip
        self._text(screen, font, intent[:58], ALARM if f.veto else TEXT, (x, y + 24))
        for n, line in enumerate(
            _wrap(("VETO: " if f.veto else "reason: ") + (f.reason or "-"), 52)[:3]
        ):
            self._text(screen, self.f_med, line, ALARM if f.veto else DIM, (x, y + 54 + 18 * n))
        self._text(screen, self.f_small, f"applied: {f.applied}"[:60], DIM, (x, y + 112))

        y = 590
        pygame.draw.line(screen, LINE, (PANEL_X, y - 6), (SIZE[0], y - 6))
        for n, line in enumerate((
            "REAL: plant, AGC/DSKY, log, target, hazards",
            "DRAWN: LM mesh (NASA, simplified), plume, grid tint",
            "3-DoF: no attitude dynamics; contact plane = altitude 0",
        )):  # fmt: skip
            self._text(screen, self.f_small, line, DIM, (x, y + 14 * n))
        self._text(screen, self.f_med, status, CAUTION, (x, y + 50))
        self._text(
            screen,
            self.f_small,
            "space pause  arrows scrub  up/down speed  1 2 3 camera  esc close",
            DIM,
            (x, 700),
        )
        if verdict:
            box = pygame.Rect(SCENE.x + 40, 40, SCENE.w - 80, 54)
            pygame.draw.rect(screen, BG, box)
            pygame.draw.rect(
                screen, ALARM if "OUTSIDE" in verdict or "NO LANDING" in verdict else DSKY, box, 2
            )
            banner = self.f_big.render(verdict, True, TEXT)
            screen.blit(
                banner,
                (box.centerx - banner.get_width() // 2, box.centery - banner.get_height() // 2),
            )

    # --- one frame ----------------------------------------------------------------------------

    def draw(
        self, screen: pygame.Surface, frames: list[ViewFrame], index: int, camera: int = 1,
        status: str = "", verdict: str | None = None,
    ) -> None:  # fmt: skip
        """`frames` is everything known so far; `index` is the one being shown."""
        screen.fill(BG)
        if not frames:
            self._text(screen, self.f_big, "waiting for the first frame...", DIM, (24, 24))
            return
        index = min(max(index, 0), len(frames) - 1)
        shown = frames[index]
        self._draw_scene(screen, frames[: index + 1], camera)
        self._draw_profile(screen, frames, index)
        self._draw_strip(screen, frames, index)
        self._draw_panel(screen, shown, status, verdict)


def _wrap(text: str, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        if len(cur) + len(word) + 1 > width and cur:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + ([cur] if cur else [])
