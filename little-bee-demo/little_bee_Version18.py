# little_bee.py
"""
Little Bee — V-shaped wings, vertical stripes, pooled particles, sounds.
Bird enemies (bigger than bee) spawn from right; head faces left.
Bird wings are sharp parallelograms; now shorter and wider.
Bee can fire stinger (F).

Controls:
 - Space / Up: flap
 - F: fire stinger
 - R: restart
 - Esc / close: quit
"""
import os
import json
import random
import sys
import math
import io
import wave
import struct
import pygame

# --- Config ---
WIDTH, HEIGHT = 800, 600
FPS = 60

BEE_START_POS = (120, HEIGHT // 2)
GRAVITY = 0.45
FLAP_STRENGTH = -9
OBSTACLE_SPEED = 4
FLOWER_SPEED = 4

SPAWN_OBSTACLE_EVERY = 1400  # ms
SPAWN_FLOWER_EVERY = 900     # ms

TRAIL_SPAWN_EVERY_MS = 80

SHAKE_DEFAULT_DURATION_MS = 420
SHAKE_DEFAULT_MAGNITUDE = 12

# Bird config
BIRD_SPAWN_EVERY_MS = 1600
BIRD_MIN_SPEED = 2.8
BIRD_MAX_SPEED = 5.0

# Stinger config
STINGER_SPEED = 12.0
STINGER_COOLDOWN_MS = 300
MAX_STINGERS = 3
STINGER_LIFE_MS = 3200  # ms

# Score file
SCORES_FILE = "scores.json"
TOP_PLAYERS_COUNT = 5
PLAYER_TOP_COUNT = 10

# Colors
BG = (135, 206, 235)
BEE_YELLOW = (255, 200, 0)
BEE_STRIPE = (0, 0, 0)
WING_FILL = (170, 210, 255, 140)
WING_OUTLINE = (20, 20, 20)
CHEEK_PINK = (255, 145, 160)
ANTENNA_COLOR = (30, 30, 30)
STINGER_COLOR = (40, 40, 40)
TEXT_COLOR = (20, 20, 20)

PARTICLE_COLORS = [
    (255, 130, 180),
    (255, 180, 210),
    (255, 220, 240),
]

pygame.init()

# Mixer init with fallback
mixer_available = True
try:
    pygame.mixer.init(frequency=44100, size=-16, channels=2)
except Exception:
    mixer_available = False

screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Little Bee")
clock = pygame.time.Clock()
font = pygame.font.SysFont("Arial", 20)
big_font = pygame.font.SysFont("Arial", 40)


# --- Sound helpers (procedural) ---
def make_tone_wav_bytes(frequencies, duration_ms=300, volume=0.4, sample_rate=44100):
    duration_s = duration_ms / 1000.0
    n_samples = int(duration_s * sample_rate)
    max_amp = int(32767 * volume)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for i in range(n_samples):
            t = i / sample_rate
            sample = 0.0
            for freq, amp in frequencies:
                sample += amp * math.sin(2.0 * math.pi * freq * t)
            envelope = 1.0 - (t / duration_s)
            sample = sample * envelope
            sample_int = max(-max_amp, min(max_amp, int(sample * max_amp)))
            wf.writeframes(struct.pack("<h", sample_int))
    buf.seek(0)
    return buf


def make_sound(frequencies, duration_ms=300, volume=0.4):
    if not mixer_available:
        return None
    wav_buf = make_tone_wav_bytes(frequencies, duration_ms=duration_ms, volume=volume)
    try:
        s = pygame.mixer.Sound(wav_buf)
        return s
    except Exception:
        return None


flap_sound = make_sound([(880, 1.0), (1320, 0.4)], duration_ms=120, volume=0.35)
collect_sound = make_sound([(880, 0.8), (1100, 0.5), (1320, 0.2)], duration_ms=220, volume=0.45)
hit_sound = make_sound([(120, 1.0), (80, 0.8)], duration_ms=380, volume=0.6)
stinger_sound = make_sound([(1500, 0.8), (2000, 0.3)], duration_ms=120, volume=0.28)
bg_sound = make_sound([(220, 0.7), (330, 0.4), (440, 0.2)], duration_ms=2000, volume=0.12)

if mixer_available and bg_sound:
    bg_channel = bg_sound.play(loops=-1)
    if bg_channel:
        bg_channel.set_volume(0.45)


# --- Particle pooling & pre-render ---
PRE_RENDERED_PARTICLES = {}


def get_prerendered_particle_surface(radius, color):
    key = (int(radius), color)
    if key in PRE_RENDERED_PARTICLES:
        return PRE_RENDERED_PARTICLES[key]
    size = int(radius * 2) + 4
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.circle(surf, color + (255,), (size // 2, size // 2), int(radius))
    PRE_RENDERED_PARTICLES[key] = surf
    return surf


particle_pool = []
active_particles = []
MAX_PARTICLES = 800


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "color", "radius", "surf")

    def __init__(self):
        self.x = self.y = self.vx = self.vy = 0.0
        self.life = self.max_life = 0
        self.color = (255, 255, 255)
        self.radius = 2.0
        self.surf = None

    def reset(self, x, y, vx, vy, life, color, radius):
        self.x, self.y, self.vx, self.vy = float(x), float(y), float(vx), float(vy)
        self.life = int(life)
        self.max_life = int(life)
        self.color = color
        self.radius = float(radius)
        self.surf = get_prerendered_particle_surface(self.radius, color)

    def update(self):
        self.vy += 0.18
        self.vx *= 0.99
        self.vy *= 0.99
        self.x += self.vx
        self.y += self.vy
        self.life -= 1

    def draw(self, surf):
        if self.life <= 0:
            return
        alpha = max(0, int(255 * (self.life / self.max_life)))
        temp = self.surf.copy()
        temp.fill((255, 255, 255, alpha), special_flags=pygame.BLEND_RGBA_MULT)
        sx = int(self.x - temp.get_width() // 2)
        sy = int(self.y - temp.get_height() // 2)
        surf.blit(temp, (sx, sy))


def spawn_particle_from_pool(x, y, vx, vy, life, color, radius):
    if len(active_particles) >= MAX_PARTICLES:
        return
    if particle_pool:
        p = particle_pool.pop()
    else:
        p = Particle()
    p.reset(x, y, vx, vy, life, color, radius)
    active_particles.append(p)


def spawn_collect_particles(x, y, count=14):
    for i in range(count):
        angle = random.uniform(0, math.pi * 2)
        speed = random.uniform(1.6, 5.0)
        vx = math.cos(angle) * speed
        vy = math.sin(angle) * speed * 0.7 - 1.2
        col = random.choice(PARTICLE_COLORS)
        spawn_particle_from_pool(x, y, vx, vy, life=random.randint(30, 60), color=col,
                                 radius=random.uniform(2.5, 5.5))


def spawn_hit_particles(x, y, count=18):
    for i in range(count):
        angle = random.uniform(0, math.pi * 2)
        speed = random.uniform(2.0, 6.0)
        vx = math.cos(angle) * speed
        vy = math.sin(angle) * speed * 0.6 - 1.0
        col = (200, 120, 80)
        spawn_particle_from_pool(x, y, vx, vy, life=random.randint(30, 70), color=col,
                                 radius=random.uniform(3.0, 6.5))


def spawn_flap_particles(x, y, count=6):
    for i in range(count):
        vx = random.uniform(-1.6, 1.6)
        vy = random.uniform(-4.0, -1.0)
        col = (255, 230, 180)
        spawn_particle_from_pool(x + random.uniform(-6, 6), y + random.uniform(6, 12), vx, vy,
                                 life=random.randint(16, 30), color=col, radius=random.uniform(1.5, 3.0))


def spawn_bee_trail(x, y):
    vx = random.uniform(-0.6, -0.2)
    vy = random.uniform(-0.6, 0.6)
    col = (255, 220, 180)
    spawn_particle_from_pool(x + random.uniform(-4, 4), y + random.uniform(2, 6), vx, vy,
                             life=random.randint(18, 30), color=col, radius=random.uniform(1.2, 2.8))


# --- Wings surface (half-size) ---
def make_wing_surf(w, h):
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.ellipse(surf, WING_FILL, (0, 0, w, h))
    outline_col = (WING_OUTLINE[0], WING_OUTLINE[1], WING_OUTLINE[2], 220)
    pygame.draw.ellipse(surf, outline_col, (0, 0, w, h), 2)
    return surf


WING_SURF = make_wing_surf(24, 16)


# --- Projectile & Enemy ---
class Stinger:
    def __init__(self, x, y):
        self.x = float(x)
        self.y = float(y)
        self.vx = STINGER_SPEED
        self.radius = 4
        self.spawn_time = pygame.time.get_ticks()
        self.rect = pygame.Rect(int(self.x - self.radius), int(self.y - self.radius), self.radius * 2,
                                self.radius * 2)

    def update(self, dt):
        self.x += self.vx
        self.rect.x = int(self.x - self.radius)
        self.rect.y = int(self.y - self.radius)

    def draw(self, surf):
        x = int(self.x); y = int(self.y)
        pygame.draw.polygon(surf, STINGER_COLOR, [(x - 2, y - 3), (x + 8, y), (x - 2, y + 3)])
        pygame.draw.circle(surf, (220, 200, 40), (x + 2, y), 2)

    def is_expired(self, now):
        return (now - self.spawn_time) > STINGER_LIFE_MS or self.x > WIDTH + 40


# --- Bird enemy (bigger than bee, head on left); wings = short & wide parallelograms ---
class Bird:
    def __init__(self):
        self.w = random.randint(64, 92)
        self.h = random.randint(34, 48)
        self.x = WIDTH + 10
        self.y = random.randint(60, HEIGHT - 80)
        self.speed = random.uniform(BIRD_MIN_SPEED, BIRD_MAX_SPEED)
        self.rect = pygame.Rect(self.x, self.y, self.w, self.h)
        self.wing_phase = random.uniform(0, 2 * math.pi)

    def update(self, dt):
        self.x -= self.speed
        self.rect.x = int(self.x)
        self.wing_phase += dt * 0.02

    def draw(self, surf):
        # draw bird facing left: head on left, tail on right
        bx = int(self.x)
        by = int(self.y)
        w, h = self.w, self.h
        cx = bx + w // 2
        cy = by + h // 2

        # body (ellipse)
        body_color = (200, 100, 40)
        pygame.draw.ellipse(surf, body_color, (bx, by, w, h))
        # belly stripe
        pygame.draw.ellipse(surf, (220, 160, 90), (bx + int(w * 0.15), by + int(h * 0.15), int(w * 0.7), int(h * 0.7)),
                            0)

        # head left (circle overlapping left of body)
        head_r = int(h * 0.6)
        head_x = bx + int(w * 0.18)
        head_y = cy - int(h * 0.12)
        pygame.draw.circle(surf, (220, 170, 90), (head_x, head_y), head_r)
        # eye (small)
        pygame.draw.circle(surf, (20, 20, 20), (head_x + int(head_r * 0.15), head_y - 2), max(2, head_r // 4))
        # beak pointing left (triangle)
        pygame.draw.polygon(surf, (180, 120, 30),
                            [(head_x - head_r - 4, head_y), (head_x - head_r + 8, head_y - 6),
                             (head_x - head_r + 8, head_y + 6)])
        # tail (right side triangle)
        pygame.draw.polygon(surf, (160, 80, 30),
                            [(bx + w - 6, cy), (bx + w + 12, cy - 8), (bx + w + 12, cy + 8)])

        # wing animation parameter
        wing_off = int(math.sin(self.wing_phase) * 5)  # flap motion magnitude (reduced for stubbier wing)

        # Parallelogram wing parameters (shorter & wider)
        # inner edge should contact the body "behind the head"
        attach_x = head_x + head_r + 4  # just behind the head on the body
        attach_y_center = cy

        # Make wings shorter (reduced length) and wider (thicker inner edge)
        wing_length = int(w * 0.45)   # shorter than before (was ~0.9)
        wing_thickness = int(h * 0.6)  # wider than before (was ~0.35)

        # angle about 45 degrees
        angle_deg = 45
        rad = math.radians(angle_deg)
        dx = int(math.cos(rad) * wing_length)
        dy = int(math.sin(rad) * wing_length)

        # wing color slightly darker than body
        def darker(col, factor=0.85):
            return (max(0, int(col[0] * factor)),
                    max(0, int(col[1] * factor)),
                    max(0, int(col[2] * factor)))

        wing_color = darker(body_color, 0.85)
        outline_color = (120, 120, 130)

        # Upper wing parallelogram (inner vertical edge contact with body)
        upper_inner_top = (attach_x, attach_y_center - wing_thickness // 2 - 4)
        upper_inner_bottom = (attach_x, attach_y_center - 4)
        upper_outer_top = (upper_inner_top[0] - dx, upper_inner_top[1] - dy - wing_off)
        upper_outer_bottom = (upper_inner_bottom[0] - dx, upper_inner_bottom[1] - dy - wing_off)
        upper_poly = [upper_inner_top, upper_inner_bottom, upper_outer_bottom, upper_outer_top]
        pygame.draw.polygon(surf, wing_color, upper_poly)
        pygame.draw.polygon(surf, outline_color, upper_poly, 2)

        # Lower wing parallelogram (inner vertical edge contact with body)
        lower_inner_top = (attach_x, attach_y_center + 4)
        lower_inner_bottom = (attach_x, attach_y_center + wing_thickness // 2 + 4)
        lower_outer_top = (lower_inner_top[0] - dx, lower_inner_top[1] + dy + wing_off)
        lower_outer_bottom = (lower_inner_bottom[0] - dx, lower_inner_bottom[1] + dy + wing_off)
        lower_poly = [lower_inner_top, lower_inner_bottom, lower_outer_bottom, lower_outer_top]
        pygame.draw.polygon(surf, wing_color, lower_poly)
        pygame.draw.polygon(surf, outline_color, lower_poly, 2)


# --- Bee (v1 style) ---
class Bee:
    def __init__(self):
        self.x, self.y = BEE_START_POS
        self.vel_y = 0
        self.radius = 18
        self.rect = pygame.Rect(self.x - self.radius, self.y - self.radius, self.radius * 2 + 18,
                                self.radius * 2)
        self.wing_phase = random.uniform(0, 2 * math.pi)
        self.wing_speed = 0.03
        self.last_shot_ms = -9999

    def flap(self):
        self.vel_y = FLAP_STRENGTH
        spawn_flap_particles(self.x - 6, self.y + self.radius // 2, count=6)
        if mixer_available and flap_sound:
            flap_sound.play()

    def can_shoot(self, now):
        return (now - self.last_shot_ms) >= STINGER_COOLDOWN_MS and len(stingers) < MAX_STINGERS

    def shoot(self, now):
        head_x = self.x + int(self.radius * 0.9)
        head_y = self.y - int(self.radius * 0.2)
        s = Stinger(head_x + 6, head_y)
        stingers.append(s)
        self.last_shot_ms = now
        if mixer_available and stinger_sound:
            stinger_sound.play()

    def update(self, dt):
        self.vel_y += GRAVITY
        self.y += self.vel_y
        if self.y < self.radius:
            self.y = self.radius;
            self.vel_y = 0
        if self.y > HEIGHT - self.radius:
            self.y = HEIGHT - self.radius;
            self.vel_y = 0
        self.rect.topleft = (int(self.x - self.radius), int(self.y - self.radius))
        speed_factor = 1.0 + min(3.0, abs(self.vel_y) * 0.08)
        self.wing_phase += dt * self.wing_speed * speed_factor

    def draw(self, surf):
        cx = int(self.x)
        cy = int(self.y)
        flap = math.sin(self.wing_phase)
        flap_delta = flap * 8.0
        left_angle = -45 + flap_delta
        right_angle = 45 - flap_delta
        left_anchor = (cx - 10, cy - self.radius + 2)
        right_anchor = (cx + 10, cy - self.radius + 2)
        lw = pygame.transform.rotozoom(WING_SURF, left_angle, 1.0)
        rw_base = pygame.transform.flip(WING_SURF, True, False)
        rw = pygame.transform.rotozoom(rw_base, right_angle, 1.0)
        lw_w, lw_h = lw.get_size()
        rw_w, rw_h = rw.get_size()
        lw_center = (left_anchor[0] - lw_w * 0.18, left_anchor[1] + lw_h * 0.04)
        rw_center = (right_anchor[0] + rw_w * 0.18, right_anchor[1] + rw_h * 0.04)
        surf.blit(lw, (int(lw_center[0] - lw_w // 2), int(lw_center[1] - lw_h // 2)))
        surf.blit(rw, (int(rw_center[0] - rw_w // 2), int(rw_center[1] - rw_h // 2)))
        pygame.draw.circle(surf, BEE_YELLOW, (cx, cy), self.radius)
        pygame.draw.circle(surf, BEE_STRIPE, (cx, cy), self.radius, 2)
        num_stripes = 3
        stripe_w = 3
        total_width = self.radius * 1.6
        spacing = total_width / (num_stripes + 1)
        for i in range(num_stripes):
            offset = (i - (num_stripes - 1) / 2.0) * spacing
            stripe_cx = cx + int(offset)
            dx = stripe_cx - cx
            if abs(dx) > self.radius:
                continue
            half_h = int(math.sqrt(max(0.0, self.radius * self.radius - dx * dx)))
            top_y = cy - half_h
            rect = pygame.Rect(stripe_cx - stripe_w // 2, top_y, stripe_w, half_h * 2)
            pygame.draw.rect(surf, BEE_STRIPE, rect, border_radius=2)
        head_r = int(self.radius * 0.65)
        head_x = cx + int(self.radius * 0.9)
        head_y = cy - int(self.radius * 0.2)
        pygame.draw.circle(surf, BEE_YELLOW, (head_x, head_y), head_r)
        pygame.draw.circle(surf, BEE_STRIPE, (head_x, head_y), head_r, 2)
        left_eye_rect = pygame.Rect(head_x - 10, head_y - 2, 10, 8)
        pygame.draw.arc(surf, BEE_STRIPE, left_eye_rect, math.pi * 0.1, math.pi * 0.9, 2)
        pygame.draw.circle(surf, BEE_STRIPE, (head_x + 6, head_y - 2), 3)
        pygame.draw.circle(surf, CHEEK_PINK, (head_x - 6, head_y + 6), 4)
        mouth_rect = pygame.Rect(head_x - 8, head_y + 2, 16, 12)
        pygame.draw.arc(surf, BEE_STRIPE, mouth_rect, math.pi * 0.15, math.pi * 0.85, 2)
        ax1 = head_x - 6;
        ay1 = head_y - head_r + 6;
        ax2 = ax1 - 8;
        ay2 = ay1 - 14
        pygame.draw.line(surf, ANTENNA_COLOR, (ax1, ay1), (ax2, ay2), 3)
        pygame.draw.circle(surf, ANTENNA_COLOR, (ax2, ay2), 4)
        bx1 = head_x + 6;
        by1 = head_y - head_r + 6;
        bx2 = bx1 + 8;
        by2 = by1 - 14
        pygame.draw.line(surf, ANTENNA_COLOR, (bx1, by1), (bx2, by2), 3)
        pygame.draw.circle(surf, ANTENNA_COLOR, (bx2, by2), 4)
        tail_x = cx - int(self.radius * 1.1)
        tail_y = cy
        pygame.draw.polygon(surf, STINGER_COLOR, [(tail_x - 4, tail_y), (tail_x + 4, tail_y - 6), (tail_x + 4, tail_y + 6)])


# --- Obstacles & Flower ---
class Obstacle:
    def __init__(self):
        w = random.randint(22, 36)
        h = random.randint(60, 160)
        top_or_bottom = random.choice(["top", "bottom"])
        if top_or_bottom == "top":
            self.rect = pygame.Rect(WIDTH + 20, 0, w, h)
        else:
            self.rect = pygame.Rect(WIDTH + 20, HEIGHT - h, w, h)
        self.speed = OBSTACLE_SPEED

    def update(self):
        self.rect.x -= self.speed

    def draw(self, surf):
        pygame.draw.rect(surf, (80, 40, 20), self.rect)
        if self.rect.top == 0:
            for i in range(0, self.rect.width, 8):
                points = [
                    (self.rect.x + i, self.rect.bottom),
                    (self.rect.x + i + 4, self.rect.bottom - 14),
                    (self.rect.x + i + 8, self.rect.bottom),
                ]
                pygame.draw.polygon(surf, (40, 20, 10), points)
        else:
            for i in range(0, self.rect.width, 8):
                points = [
                    (self.rect.x + i, self.rect.top),
                    (self.rect.x + i + 4, self.rect.top + 14),
                    (self.rect.x + i + 8, self.rect.top),
                ]
                pygame.draw.polygon(surf, (40, 20, 10), points)


class Flower:
    def __init__(self):
        size = random.randint(14, 22)
        self.x = WIDTH + 20
        self.y = random.randint(60, HEIGHT - 60)
        self.size = size
        self.rect = pygame.Rect(self.x - size // 2, self.y - size // 2, size, size)
        self.speed = FLOWER_SPEED

    def update(self):
        self.x -= self.speed
        self.rect.x = int(self.x - self.size // 2)

    def draw(self, surf):
        cx, cy = int(self.x), int(self.y)
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            px = cx + int((self.size // 2 + 4) * math.cos(rad))
            py = cy + int((self.size // 2 + 4) * math.sin(rad))
            pygame.draw.circle(surf, (255, 105, 180), (px, py), max(3, self.size // 6))
        pygame.draw.circle(surf, (255, 255, 150), (cx, cy), max(4, self.size // 4))


# --- Globals ---
stingers = []
birds = []


# --- Score persistence helpers ---
def load_scores(path=SCORES_FILE):
    if not os.path.exists(path):
        return {"players": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"players": {}}


def save_scores(data, path=SCORES_FILE):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def record_score_for_player(name, score):
    data = load_scores()
    players = data.setdefault("players", {})
    scores = players.setdefault(name, [])
    scores.append(int(score))
    scores.sort(reverse=True)
    players[name] = scores[:PLAYER_TOP_COUNT]
    save_scores(data)


def get_top_players(data, top=TOP_PLAYERS_COUNT):
    players = data.get("players", {})
    best = []
    for name, scores in players.items():
        if scores:
            best.append((name, max(scores)))
    best.sort(key=lambda x: x[1], reverse=True)
    return best[:top]


def get_player_top_scores(name, data, top=PLAYER_TOP_COUNT):
    players = data.get("players", {})
    return players.get(name, [])[:top]


# --- UI helper ---
def draw_multiline_text(surf, lines, x, y, size=20, color=(20, 20, 20)):
    f = pygame.font.SysFont("Arial", size)
    oy = 0
    for line in lines:
        img = f.render(line, True, color)
        surf.blit(img, (x, y + oy))
        oy += int(size * 1.15)


# --- Main loop ---
def main():
    player_name = input("Enter player name: ").strip() or "Player"

    bee = Bee()
    obstacles = []
    flowers = []
    score = 0
    flowers_collected = 0
    birds_killed = 0
    last_obstacle = pygame.time.get_ticks()
    last_flower = pygame.time.get_ticks()
    last_bird = pygame.time.get_ticks()
    running = True
    game_over = False
    recorded_score = False
    leaderboard_data = None
    player_top_scores = []
    trail_timer_ms = 0
    lives = 3

    while running:
        dt = clock.tick(FPS)
        now = pygame.time.get_ticks()

        # Events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_SPACE, pygame.K_UP) and not game_over:
                    bee.flap()
                if event.key == pygame.K_f and not game_over:
                    if bee.can_shoot(now):
                        bee.shoot(now)
                if event.key == pygame.K_r and game_over:
                    bee = Bee()
                    obstacles = []
                    flowers = []
                    birds[:] = []
                    stingers[:] = []
                    score = 0
                    flowers_collected = 0
                    birds_killed = 0
                    last_obstacle = now
                    last_flower = now
                    last_bird = now
                    recorded_score = False
                    leaderboard_data = None
                    player_top_scores = []
                    trail_timer_ms = 0
                    lives = 3
                    game_over = False
                if event.key == pygame.K_ESCAPE:
                    running = False

        if not game_over:
            # spawn
            if now - last_obstacle > SPAWN_OBSTACLE_EVERY:
                obstacles.append(Obstacle())
                last_obstacle = now
            if now - last_flower > SPAWN_FLOWER_EVERY:
                flowers.append(Flower())
                last_flower = now
            if now - last_bird > BIRD_SPAWN_EVERY_MS:
                birds.append(Bird())
                last_bird = now

            # update
            bee.update(dt)
            for ob in obstacles:
                ob.update()
            for f in flowers:
                f.update()
            for b in birds:
                b.update(dt)
            for s in stingers:
                s.update(dt)

            # trail
            trail_timer_ms += dt
            if trail_timer_ms >= TRAIL_SPAWN_EVERY_MS:
                trail_timer_ms %= TRAIL_SPAWN_EVERY_MS
                spawn_bee_trail(bee.x - 8, bee.y + bee.radius // 2)

            # cleanup (in-place)
            obstacles = [o for o in obstacles if o.rect.right > -50]
            flowers = [f for f in flowers if f.x > -50]
            birds[:] = [b for b in birds if b.x + b.w > -60]
            stingers[:] = [s for s in stingers if not s.is_expired(now) and s.x < WIDTH + 60]

            # collisions
            for ob in obstacles[:]:
                if ob.rect.colliderect(bee.rect):
                    obstacles.remove(ob)
                    lives -= 1
                    bee.x = max(60, bee.x - 24)
                    bee.vel_y = -6
                    spawn_hit_particles(bee.x, bee.y, count=16)
                    if mixer_available and hit_sound:
                        hit_sound.play()
                    if lives <= 0:
                        game_over = True
                        break

            for f in flowers[:]:
                if bee.rect.colliderect(f.rect):
                    fx, fy = f.x, f.y
                    flowers.remove(f)
                    flowers_collected += 1
                    score += 1
                    spawn_collect_particles(fx, fy, count=14)
                    if mixer_available and collect_sound:
                        collect_sound.play()

            for b in birds[:]:
                if b.rect.colliderect(bee.rect):
                    try:
                        birds.remove(b)
                    except ValueError:
                        pass
                    lives -= 1
                    bee.x = max(60, bee.x - 24)
                    bee.vel_y = -6
                    spawn_hit_particles(bee.x, bee.y, count=20)
                    if mixer_available and hit_sound:
                        hit_sound.play()
                    if lives <= 0:
                        game_over = True
                        break

            for s in stingers[:]:
                for b in birds[:]:
                    if b.rect.colliderect(s.rect):
                        try:
                            birds.remove(b)
                        except ValueError:
                            pass
                        try:
                            stingers.remove(s)
                        except ValueError:
                            pass
                        birds_killed += 1
                        score += 2
                        spawn_collect_particles(b.x + b.w / 2, b.y + b.h / 2, count=10)
                        if mixer_available and collect_sound:
                            collect_sound.play()
                        break

        # update particles
        for p in active_particles[:]:
            p.update()
            if p.life <= 0 or p.y > HEIGHT + 60:
                active_particles.remove(p)
                if len(particle_pool) < MAX_PARTICLES:
                    particle_pool.append(p)

        # On game over: record score once and load leaderboards
        if game_over and not recorded_score:
            total_score = score
            record_score_for_player(player_name, total_score)
            leaderboard_data = load_scores()
            player_top_scores = get_player_top_scores(player_name, leaderboard_data, PLAYER_TOP_COUNT)
            recorded_score = True

        # Draw
        screen.fill(BG)
        pygame.draw.rect(screen, (40, 160, 40), (0, HEIGHT - 60, WIDTH, 60))
        for i in range(3):
            cx_cloud = (pygame.time.get_ticks() // (20 + i * 10) + i * 200) % (WIDTH + 200) - 100
            pygame.draw.ellipse(screen, (255, 255, 255), (cx_cloud, 70 + i * 20, 120, 50))

        for f in flowers:
            f.draw(screen)
        for ob in obstacles:
            ob.draw(screen)

        for b in birds:
            b.draw(screen)

        for s in stingers:
            s.draw(screen)

        bee.draw(screen)

        for p in active_particles:
            p.draw(screen)

        def draw_text_local(surf, text, x, y, size=20):
            surf.blit(pygame.font.SysFont("Arial", size).render(text, True, TEXT_COLOR), (x, y))

        draw_text_local(screen, f"Player: {player_name}", 10, 8)
        draw_text_local(screen, f"Flowers: {flowers_collected}", 10, 34)
        draw_text_local(screen, f"Birds killed: {birds_killed}", 10, 58)
        draw_text_local(screen, f"Score: {score}", 10, 82)
        draw_text_local(screen, f"Lives: {lives}", 10, 106)
        draw_text_local(screen, "Press F to shoot", 10, 130)

        # Game Over overlay
        if game_over:
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 120))
            screen.blit(overlay, (0, 0))
            go_text = big_font.render("GAME OVER", True, (255, 220, 30))
            screen.blit(go_text, (WIDTH // 2 - go_text.get_width() // 2, HEIGHT // 2 - 140))
            summary_lines = [
                f"Player: {player_name}",
                f"Flowers collected: {flowers_collected}",
                f"Birds killed: {birds_killed}",
                f"Total score: {score}",
            ]
            draw_multiline_text(screen, summary_lines, WIDTH // 2 - 160, HEIGHT // 2 - 80, size=20, color=(255, 255, 255))

            if leaderboard_data is None:
                leaderboard_data = load_scores()
            top_players = get_top_players(leaderboard_data, TOP_PLAYERS_COUNT)
            left_x = WIDTH // 2 - 360
            top_y = HEIGHT // 2 - 40
            draw_multiline_text(screen, ["Top Players:"], left_x, top_y, size=20, color=(255, 255, 255))
            ly = top_y + 26
            for idx, (name, best) in enumerate(top_players):
                line = f"{idx + 1}. {name} - {best}"
                draw_multiline_text(screen, [line], left_x, ly, size=18, color=(255, 255, 255))
                ly += 22

            right_x = WIDTH // 2 + 40
            draw_multiline_text(screen, [f"{player_name} Top Scores:"], right_x, top_y, size=20, color=(255, 255, 255))
            ry = top_y + 26
            for idx, s in enumerate(player_top_scores[:PLAYER_TOP_COUNT]):
                draw_multiline_text(screen, [f"{idx + 1}. {s}"], right_x, ry, size=18, color=(255, 255, 255))
                ry += 22

            draw_multiline_text(screen, ["Press R to restart"], WIDTH // 2 - 80, HEIGHT // 2 + 120, size=20, color=(255, 255, 255))

        pygame.display.flip()

    # cleanup
    if mixer_available:
        try:
            pygame.mixer.stop()
            pygame.mixer.quit()
        except Exception:
            pass
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()