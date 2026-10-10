import asyncio
import math
import random
import sys
from array import array
from functools import lru_cache

import pygame 



WIDTH = 1280
HEIGHT = 720
FPS = 60
ROUND_TIME = 60.0

BACKGROUND = (7, 10, 22)
GRID = (19, 32, 55)
CYAN = (45, 232, 255)
RED = (255, 55, 78)
GOLD = (255, 211, 91)
WHITE = (226, 241, 255)
MUTED = (112, 147, 174)
AUDIO_SAMPLE_RATE = 22050
WEB_BUILD = sys.platform == "emscripten"


@lru_cache(maxsize=8)
def make_glow(radius, color):
    size = radius * 4
    glow = pygame.Surface((size, size), pygame.SRCALPHA)
    center = size // 2
    for layer in range(9, 0, -1):
        ring_radius = int(radius * layer / 3)
        alpha = max(3, int(30 * (1 - layer / 10) ** 2))
        pygame.draw.circle(glow, (*color, alpha), (center, center), ring_radius)
    return glow


@lru_cache(maxsize=32)
def make_panel(size, fill, border):
    panel = pygame.Surface(size, pygame.SRCALPHA)
    pygame.draw.rect(panel, fill, panel.get_rect(), border_radius=12)
    pygame.draw.rect(panel, (*border, 105), panel.get_rect(), width=1, border_radius=12)
    return panel


def draw_text(surface, font, text, color, position, anchor="topleft"):
    image = font.render(text, True, color)
    rect = image.get_rect()
    setattr(rect, anchor, position)
    surface.blit(image, rect)


def draw_panel(surface, rect, fill=(10, 18, 34, 225), border=(45, 232, 255)):
    surface.blit(make_panel(rect.size, fill, border), rect)


class SynthAudio:
    def __init__(self):
        self.enabled = pygame.mixer.get_init() is not None
        self.music_channel = None
        self.sounds = {}
        if not self.enabled:
            return

        self.sounds = {
            "countdown_3": self.make_sound(0.16, ((880, 790, 0.8),), 0.34),
            "countdown_2": self.make_sound(0.16, ((1046, 930, 0.8),), 0.34),
            "countdown_1": self.make_sound(0.2, ((1318, 1180, 0.85),), 0.38),
            "pickup": self.make_sound(
                0.34,
                ((520, 1040, 0.54), (780, 1560, 0.24)),
                0.3,
            ),
            "impact": self.make_sound(
                0.46,
                ((105, 42, 0.7), (680, 90, 0.24)),
                0.38,
                noise=0.38,
            ),
            "breach": self.make_sound(
                1.8,
                ((1280, 190, 0.45), (640, 92, 0.3), (1930, 850, 0.11)),
                0.36,
                noise=0.11,
            ),
            "ambient": self.make_ambient_loop(4.0),
        }

    @staticmethod
    def make_sound(duration, voices, volume, noise=0.0):
        sample_count = int(AUDIO_SAMPLE_RATE * duration)
        rng = random.Random(41 + sample_count)
        samples = array("h")
        attack_samples = max(1, int(AUDIO_SAMPLE_RATE * 0.012))
        release_samples = max(1, int(AUDIO_SAMPLE_RATE * min(0.12, duration * 0.35)))

        for index in range(sample_count):
            time = index / AUDIO_SAMPLE_RATE
            envelope = min(1.0, index / attack_samples)
            envelope *= min(1.0, (sample_count - index) / release_samples)
            sample = 0.0
            for start_frequency, end_frequency, amplitude in voices:
                sweep = (end_frequency - start_frequency) / duration
                phase = math.tau * (
                    start_frequency * time + 0.5 * sweep * time * time
                )
                sample += math.sin(phase) * amplitude
            if noise:
                sample += rng.uniform(-1.0, 1.0) * noise * (1.0 - time / duration)
            value = int(max(-1.0, min(1.0, sample * envelope * volume)) * 32767)
            samples.append(value)

        return pygame.mixer.Sound(buffer=samples.tobytes())

    @staticmethod
    def make_ambient_loop(duration):
        sample_count = int(AUDIO_SAMPLE_RATE * duration)
        samples = array("h")
        for index in range(sample_count):
            time = index / AUDIO_SAMPLE_RATE
            phase = math.tau * time
            drone = (
                math.sin(phase * 55) * 0.34
                + math.sin(phase * 82) * 0.2
                + math.sin(phase * 110 + math.sin(phase * 0.25) * 0.12) * 0.11
                + math.sin(phase * 164) * 0.055
            )
            value = int(drone * 0.16 * 32767)
            samples.append(value)
        return pygame.mixer.Sound(buffer=samples.tobytes())

    def play(self, name, volume=1.0):
        sound = self.sounds.get(name)
        if not self.enabled or sound is None:
            return
        channel = sound.play()
        if channel is not None:
            channel.set_volume(volume)

    def start_background(self):
        if not self.enabled:
            return
        self.stop_background()
        sound = self.sounds["ambient"]
        self.music_channel = sound.play(loops=-1)
        if self.music_channel is not None:
            self.music_channel.set_volume(0.22)

    def stop_background(self, fade_ms=700):
        if self.music_channel is not None:
            if self.music_channel.get_busy():
                self.music_channel.fadeout(fade_ms)
            self.music_channel = None


class Player:
    RADIUS = 15
    SPEED = 310.0

    def __init__(self):
        self.position = pygame.Vector2(WIDTH / 2, HEIGHT / 2)
        self.facing = pygame.Vector2(1, 0)
        self.pulse = 0.0
        self.glow = make_glow(52, CYAN).copy()
        self.boost_glow = make_glow(68, CYAN).copy()
        self.glow_boost = 0.0
        self.moving = False

    def update(self, keys, dt, touch_direction=(0, 0)):
        direction = pygame.Vector2(
            float(keys[pygame.K_d] or keys[pygame.K_RIGHT])
            - float(keys[pygame.K_a] or keys[pygame.K_LEFT]),
            float(keys[pygame.K_s] or keys[pygame.K_DOWN])
            - float(keys[pygame.K_w] or keys[pygame.K_UP]),
        )
        direction += pygame.Vector2(touch_direction)
        self.moving = direction.length_squared() > 0
        if direction.length_squared() > 0:
            direction = direction.normalize()
            self.facing = direction
            self.position += direction * self.SPEED * dt

        self.position.x = max(self.RADIUS + 24, min(WIDTH - self.RADIUS - 24, self.position.x))
        self.position.y = max(self.RADIUS + 24, min(HEIGHT - self.RADIUS - 24, self.position.y))
        self.pulse += dt

    def draw(self, surface):
        center = self.position
        pulse_radius = self.RADIUS + 8 + math.sin(self.pulse * 5) * 2
        if self.glow_boost > 0:
            strength = self.glow_boost / 0.42
            self.boost_glow.set_alpha(int(255 * strength))
            surface.blit(
                self.boost_glow,
                self.boost_glow.get_rect(center=(round(center.x), round(center.y))),
            )
        glow = self.glow
        glow.set_alpha(int(218 + math.sin(self.pulse * 3.2) * 28))
        surface.blit(glow, glow.get_rect(center=(round(center.x), round(center.y))))
        pygame.draw.circle(surface, (8, 32, 48), center, self.RADIUS + 3)
        pygame.draw.circle(surface, (18, 142, 166), center, self.RADIUS, width=2)
        pygame.draw.circle(surface, (184, 250, 255), center, 6)
        pygame.draw.circle(surface, CYAN, center, 3)
        pygame.draw.circle(surface, CYAN, center, int(pulse_radius), width=1)
        tip = center + self.facing * 23
        pygame.draw.line(surface, (184, 250, 255), center, tip, 2)


class Drone:
    RADIUS = 17

    def __init__(self, position):
        self.position = pygame.Vector2(position)
        self.speed = random.uniform(76.0, 112.0)
        self.phase = random.uniform(0, math.tau)
        self.angle = 0.0
        self.glow = make_glow(48, RED).copy()

    def update(self, target, dt):
        offset = target - self.position
        if offset.length_squared() > 0:
            direction = offset.normalize()
            desired_angle = math.atan2(direction.y, direction.x)
            angle_delta = math.atan2(
                math.sin(desired_angle - self.angle),
                math.cos(desired_angle - self.angle),
            )
            self.angle += angle_delta * min(1.0, dt * 9.0)
            self.position += direction * self.speed * dt
        self.phase += dt * 4

    def draw(self, surface):
        center = self.position
        surface.blit(self.glow, self.glow.get_rect(center=(round(center.x), round(center.y))))
        direction = pygame.Vector2(math.cos(self.angle), math.sin(self.angle))
        perpendicular = pygame.Vector2(-direction.y, direction.x)
        nose = center + direction * 21
        rear_left = center - direction * 12 + perpendicular * 12
        rear_right = center - direction * 12 - perpendicular * 12
        hull = [(nose.x, nose.y), (rear_left.x, rear_left.y), (rear_right.x, rear_right.y)]

        pygame.draw.circle(surface, (65, 13, 28), center, self.RADIUS + 6, width=1)
        pygame.draw.polygon(surface, (40, 15, 28), hull)
        pygame.draw.polygon(surface, RED, hull, width=2)
        eye = center + direction * 5
        pygame.draw.circle(surface, (255, 204, 207), eye, 4)
        wing_offset = math.sin(self.phase) * 2
        for sign in (-1, 1):
            wing = center - direction * 5 + perpendicular * (sign * (15 + wing_offset))
            pygame.draw.circle(surface, (255, 115, 125), wing, 3)


class EnergyOrb:
    RADIUS = 9

    def __init__(self, position):
        self.position = pygame.Vector2(position)
        self.phase = random.uniform(0, math.tau)
        self.glow = make_glow(36, GOLD).copy()

    def update(self, dt):
        self.phase += dt * 3

    def draw(self, surface):
        center = self.position
        center_point = (round(center.x), round(center.y))
        self.glow.set_alpha(int(205 + math.sin(self.phase * 2) * 42))
        surface.blit(self.glow, self.glow.get_rect(center=center_point))
        radius = self.RADIUS + math.sin(self.phase * 2) * 1.5
        rotation = self.phase
        points = []
        for index in range(4):
            angle = rotation + index * math.pi / 2
            points.append(
                (
                    center.x + math.cos(angle) * radius,
                    center.y + math.sin(angle) * radius,
                )
            )
        pygame.draw.polygon(surface, (74, 51, 16), points)
        pygame.draw.polygon(surface, GOLD, points, width=2)
        pygame.draw.circle(surface, (255, 252, 218), center, 3)


class Particle:
    def __init__(
        self,
        position,
        color,
        rng,
        speed_range=(45, 190),
        life_range=(0.35, 0.75),
        size_range=(2, 4),
    ):
        self.position = pygame.Vector2(position)
        angle = rng.uniform(0, math.tau)
        speed = rng.uniform(*speed_range)
        self.velocity = pygame.Vector2(math.cos(angle), math.sin(angle)) * speed
        self.color = color
        self.life = rng.uniform(*life_range)
        self.max_life = self.life
        self.size = rng.randint(*size_range)
        self.glow = make_glow(5, color).copy()

    def update(self, dt):
        self.position += self.velocity * dt
        self.velocity *= math.exp(-2.4 * dt)
        self.life -= dt

    def draw(self, surface):
        progress = max(0.0, self.life / self.max_life)
        alpha = int(220 * progress)
        glow = self.glow
        glow.set_alpha(alpha)
        center = (round(self.position.x), round(self.position.y))
        surface.blit(glow, glow.get_rect(center=center))
        radius = max(1, round(self.size * (0.55 + progress * 0.45)))
        tint = tuple(channel * alpha // 255 for channel in self.color)
        pygame.draw.circle(surface, tint, center, radius)
        if self.velocity.length_squared() > 1600:
            tail = self.position - self.velocity * 0.035
            tail_color = tuple(channel * alpha // 255 for channel in self.color)
            pygame.draw.line(surface, tail_color, tail, self.position, max(1, radius))


class RadialPulse:
    def __init__(self, position, color, duration, max_radius, rng):
        self.position = pygame.Vector2(position)
        self.color = color
        self.duration = duration
        self.life = duration
        self.max_radius = max_radius
        self.glow = make_glow(64, color).copy()
        self.ring_layer = pygame.Surface(
            (max_radius * 2 + 4, max_radius * 2 + 4),
            pygame.SRCALPHA,
        )
        self.phase = rng.uniform(0, math.tau)

    def update(self, dt):
        self.life = max(0.0, self.life - dt)
        self.phase += dt * 8

    def draw(self, surface):
        progress = 1.0 - self.life / self.duration
        fade = max(0, int(230 * (1.0 - progress) ** 1.4))
        center = (round(self.position.x), round(self.position.y))
        self.glow.set_alpha(fade)
        surface.blit(self.glow, self.glow.get_rect(center=center))

        radius = max(1, int(self.max_radius * progress))
        pulse_radius = radius * (1.0 + math.sin(self.phase) * 0.025)
        self.ring_layer.fill((0, 0, 0, 0))
        ring_center = (self.ring_layer.get_width() // 2, self.ring_layer.get_height() // 2)
        pygame.draw.circle(
            self.ring_layer,
            (*self.color, fade),
            ring_center,
            max(1, round(pulse_radius)),
            width=max(1, int(4 * (1.0 - progress))),
        )
        surface.blit(self.ring_layer, self.ring_layer.get_rect(center=center))


class AmbientParticle:
    def __init__(self):
        self.position = pygame.Vector2(
            random.randrange(WIDTH),
            random.randrange(HEIGHT),
        )
        self.speed = random.uniform(4, 14)
        self.phase = random.uniform(0, math.tau)
        self.size = random.choice((1, 1, 1, 2))

    def update(self, dt):
        self.position.y -= self.speed * dt
        self.phase += dt * 2
        if self.position.y < 20:
            self.position.y = HEIGHT - 20
            self.position.x = random.randrange(20, WIDTH - 20)

    def draw(self, surface):
        brightness = int(90 + (math.sin(self.phase) + 1) * 45)
        color = (brightness // 2, brightness, min(255, brightness + 35))
        pygame.draw.circle(surface, color, self.position, self.size)


class TerminalParticle:
    def __init__(self, rng):
        edge = rng.randrange(4)
        if edge == 0:
            self.position = pygame.Vector2(rng.randrange(WIDTH), -8)
        elif edge == 1:
            self.position = pygame.Vector2(WIDTH + 8, rng.randrange(HEIGHT))
        elif edge == 2:
            self.position = pygame.Vector2(rng.randrange(WIDTH), HEIGHT + 8)
        else:
            self.position = pygame.Vector2(-8, rng.randrange(HEIGHT))
        self.speed = rng.uniform(55, 145)
        self.size = rng.choice((1, 1, 2, 2, 3))
        self.color = rng.choice((CYAN, (103, 195, 219), (179, 219, 229), WHITE))
        self.phase = rng.uniform(0, math.tau)

    def update(self, dt):
        to_center = pygame.Vector2(WIDTH / 2, HEIGHT / 2) - self.position
        if to_center.length_squared() > 1:
            self.position += to_center.normalize() * self.speed * dt
        self.phase += dt * 5

    def draw(self, surface):
        alpha = int(105 + (math.sin(self.phase) + 1) * 65)
        color = tuple(channel * alpha // 255 for channel in self.color)
        pygame.draw.circle(surface, color, self.position, self.size)


class NanoEscapeGame:
    def __init__(self, screen):
        self.screen = screen
        self.window = pygame.display.get_surface() or screen
        self.clock = pygame.time.Clock()
        self.touch_fingers = {}
        self.mouse_touch_action = None
        self.audio = SynthAudio()
        self.font = pygame.font.SysFont("consolas", 21)
        self.small_font = pygame.font.SysFont("consolas", 15)
        self.title_font = pygame.font.SysFont("consolas", 54, bold=True)
        self.state_font = pygame.font.SysFont("consolas", 38, bold=True)
        self.logo_font = pygame.font.SysFont("consolas", 58, bold=True)
        self.countdown_font = pygame.font.SysFont("consolas", 104, bold=True)
        self.impact_cue = self.state_font.render(
            "CRITICAL  //  SIGNAL BREACH",
            True,
            (255, 112, 126),
        )
        self.flash_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.overlay_shade = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.overlay_shade.fill((3, 6, 15, 190))
        self.cue_line = pygame.Surface((430, 2), pygame.SRCALPHA)
        self.terminal_text_font = pygame.font.SysFont("consolas", 27, bold=True)
        self.terminal_particle_font = pygame.font.SysFont("consolas", 16)
        self.terminal_particles = []
        self.terminal_elapsed = 0.0
        self.terminal_progress_duration = 6.0
        self.terminal_reveal_time = 6.8
        self.terminal_completed_text = self.terminal_text_font.render(
            "System breached, mission complete.",
            True,
            CYAN,
        )
        self.scanline_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        for y in range(0, HEIGHT, 4):
            pygame.draw.line(self.scanline_surface, (0, 4, 12, 34), (0, y), (WIDTH, y))
        self.fade_surface = pygame.Surface((WIDTH, HEIGHT))
        self.touch_controls_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.fade_alpha = 0
        self.fade_mode = "in"
        self.display_score = 0.0
        self.transition_from = "title"
        self.countdown_elapsed = 0.0
        self.countdown_sound_step = -1
        self.scene_time = 0.0
        self.background = self.make_background()
        self.grid_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.vignette = self.make_vignette()
        self.ambient_particles = [AmbientParticle() for _ in range(72)]
        self.fx_rng = random.Random()
        self.particles = []
        self.radial_pulses = []
        self.trail_timer = 0.0
        self.restart()
        self.state = "title"
        self.fade_alpha = 255

    def make_background(self):
        background = pygame.Surface((WIDTH, HEIGHT))
        for y in range(HEIGHT):
            blend = y / HEIGHT
            color = (
                int(BACKGROUND[0] + 4 * blend),
                int(BACKGROUND[1] + 5 * blend),
                int(BACKGROUND[2] + 12 * blend),
            )
            pygame.draw.line(background, color, (0, y), (WIDTH, y))

        for _ in range(90):
            x = random.randrange(20, WIDTH - 20)
            y = random.randrange(20, HEIGHT - 20)
            pygame.draw.circle(background, (35, 61, 83), (x, y), 1)

        for margin, color in ((15, (28, 85, 107)), (21, (15, 52, 72))):
            pygame.draw.rect(
                background,
                color,
                (margin, margin, WIDTH - margin * 2, HEIGHT - margin * 2),
                width=1,
                border_radius=12,
            )
        return background

    def make_vignette(self):
        small = pygame.Surface((160, 90), pygame.SRCALPHA)
        for y in range(90):
            for x in range(160):
                dx = (x - 79.5) / 79.5
                dy = (y - 44.5) / 44.5
                edge = min(1.0, max(0.0, (dx * dx + dy * dy - 0.36) / 1.25))
                small.set_at((x, y), (0, 2, 10, int(edge * 174)))
        return pygame.transform.smoothscale(small, (WIDTH, HEIGHT))

    def restart(self):
        self.player = Player()
        self.drones = []
        self.orbs = []
        self.particles.clear()
        self.radial_pulses.clear()
        self.score = 0
        self.display_score = 0.0
        self.time_left = ROUND_TIME
        self.elapsed = 0.0
        self.drone_spawn_timer = 2.5
        self.orb_spawn_timer = 0.0
        self.state = "playing"
        self.screen_flash_time = 0.0
        self.camera_shake_time = 0.0
        self.camera_shake_strength = 0.0
        self.impact_cue_time = 0.0
        self.terminal_elapsed = 0.0
        self.terminal_particles.clear()
        self.trail_timer = 0.0
        self.countdown_sound_step = -1

        for _ in range(3):
            self.spawn_drone()
        for _ in range(5):
            self.spawn_orb()

    def random_spawn_position(self, margin=48):
        return pygame.Vector2(
            random.uniform(margin, WIDTH - margin),
            random.uniform(margin, HEIGHT - margin),
        )

    def spawn_drone(self):
        for _ in range(20):
            position = self.random_spawn_position()
            if position.distance_to(self.player.position) > 220:
                self.drones.append(Drone(position))
                return

    def spawn_orb(self):
        for _ in range(30):
            position = self.random_spawn_position(70)
            if position.distance_to(self.player.position) < 80:
                continue
            if any(position.distance_to(drone.position) < 70 for drone in self.drones):
                continue
            if any(position.distance_to(orb.position) < 55 for orb in self.orbs):
                continue
            self.orbs.append(EnergyOrb(position))
            return

    def update(self, dt):
        self.scene_time += dt
        self.display_score += (self.score - self.display_score) * (1.0 - math.exp(-9.0 * dt))
        if self.state == "ending":
            self.terminal_elapsed += dt
            for particle in self.terminal_particles:
                particle.update(dt)
            if self.terminal_elapsed < self.terminal_progress_duration:
                while len(self.terminal_particles) < 90:
                    self.terminal_particles.append(TerminalParticle(self.fx_rng))
                self.terminal_particles = [
                    particle
                    for particle in self.terminal_particles
                    if particle.position.distance_squared_to((WIDTH / 2, HEIGHT / 2)) > 18 ** 2
                ]
            return

        for particle in self.ambient_particles:
            particle.update(dt)
        for particle in self.particles:
            particle.update(dt)
        self.particles = [particle for particle in self.particles if particle.life > 0]
        for pulse in self.radial_pulses:
            pulse.update(dt)
        self.radial_pulses = [pulse for pulse in self.radial_pulses if pulse.life > 0]
        self.screen_flash_time = max(0.0, self.screen_flash_time - dt)
        self.camera_shake_time = max(0.0, self.camera_shake_time - dt)
        self.impact_cue_time = max(0.0, self.impact_cue_time - dt)
        self.player.glow_boost = max(0.0, self.player.glow_boost - dt)

        if self.state == "transition_out":
            self.fade_alpha = min(255, self.fade_alpha + dt * 510)
            if self.fade_alpha >= 255:
                self.restart()
                self.state = "countdown"
                self.countdown_elapsed = 0.0
                self.fade_alpha = 255
                self.fade_mode = "in"
            return

        if self.fade_mode == "in" and self.fade_alpha > 0:
            self.fade_alpha = max(0, self.fade_alpha - dt * 510)
            if self.fade_alpha == 0:
                self.fade_mode = "none"

        if self.state == "title":
            return

        if self.state == "countdown":
            if self.fade_mode == "none":
                countdown_step = min(3, int(self.countdown_elapsed / 0.8))
                if countdown_step > self.countdown_sound_step and countdown_step < 3:
                    self.audio.play(f"countdown_{3 - countdown_step}", 0.8)
                    self.countdown_sound_step = countdown_step
                self.countdown_elapsed += dt
                if self.countdown_elapsed >= 3.2:
                    self.state = "playing"
                    self.elapsed = 0.0
                    self.fade_alpha = 255
                    self.fade_mode = "in"
                    self.audio.start_background()
            return

        if self.state != "playing":
            return

        self.elapsed += dt
        self.time_left = max(0.0, self.time_left - dt)
        keys = pygame.key.get_pressed()
        self.player.update(keys, dt, self.touch_direction())
        self.trail_timer -= dt
        if self.player.moving and self.trail_timer <= 0:
            trail_position = self.player.position - self.player.facing * 12
            self.particles.append(
                Particle(
                    trail_position,
                    CYAN,
                    self.fx_rng,
                    speed_range=(5, 28),
                    life_range=(0.16, 0.32),
                    size_range=(1, 2),
                )
            )
            self.trail_timer = 0.055

        for drone in self.drones:
            drone.update(self.player.position, dt)
        for orb in self.orbs:
            orb.update(dt)

        self.drone_spawn_timer -= dt
        if self.drone_spawn_timer <= 0:
            if len(self.drones) < 9:
                self.spawn_drone()
            self.drone_spawn_timer = max(1.5, 3.2 - self.elapsed * 0.025)

        self.orb_spawn_timer -= dt
        if self.orb_spawn_timer <= 0:
            if len(self.orbs) < 6:
                self.spawn_orb()
            self.orb_spawn_timer = 3.5

        remaining_orbs = []
        for orb in self.orbs:
            if self.player.position.distance_to(orb.position) <= Player.RADIUS + EnergyOrb.RADIUS:
                self.score += 100
                self.audio.play("pickup", 0.7)
                self.player.glow_boost = 0.42
                self.radial_pulses.append(
                    RadialPulse(orb.position, GOLD, 0.48, 112, self.fx_rng)
                )
                self.particles.extend(
                    Particle(
                        orb.position,
                        self.fx_rng.choice((GOLD, (255, 246, 196), CYAN)),
                        self.fx_rng,
                        speed_range=(95, 290),
                        life_range=(0.32, 0.68),
                        size_range=(2, 5),
                    )
                    for _ in range(30)
                )
            else:
                remaining_orbs.append(orb)
        self.orbs = remaining_orbs

        if self.time_left <= 0:
            self.state = "ending"
            self.audio.stop_background()
            self.audio.play("breach", 0.65)
            self.terminal_elapsed = 0.0
            self.terminal_particles = [
                TerminalParticle(self.fx_rng) for _ in range(90)
            ]
        elif any(
            self.player.position.distance_to(drone.position) <= Player.RADIUS + Drone.RADIUS
            for drone in self.drones
        ):
            self.state = "game_over"
            self.trigger_collision_effect()

    def trigger_collision_effect(self):
        self.audio.stop_background(450)
        self.audio.play("impact", 0.75)
        self.screen_flash_time = 0.24
        self.camera_shake_time = 0.46
        self.camera_shake_strength = 15.0
        self.impact_cue_time = 1.15
        self.player.glow_boost = 0.22
        self.radial_pulses.append(
            RadialPulse(self.player.position, RED, 0.72, 260, self.fx_rng)
        )
        explosion_colors = (RED, (255, 126, 73), (255, 227, 188), CYAN)
        self.particles.extend(
            Particle(
                self.player.position,
                self.fx_rng.choice(explosion_colors),
                self.fx_rng,
                speed_range=(90, 520),
                life_range=(0.48, 1.12),
                size_range=(2, 7),
            )
            for _ in range(88)
        )

    def draw_hud(self):
        draw_panel(self.screen, pygame.Rect(30, 25, 368, 96), (5, 14, 29, 220))
        draw_text(self.screen, self.small_font, "N A N O   / /   E S C A P E", CYAN, (50, 40))
        draw_text(self.screen, self.small_font, "SURVIVAL PROTOCOL  •  ACTIVE", MUTED, (50, 62))
        shown_score = int(self.display_score)
        draw_text(self.screen, self.font, f"{shown_score:06d}", WHITE, (50, 82))
        draw_text(self.screen, self.small_font, "ENERGY SCORE", CYAN, (168, 89))
        pygame.draw.line(self.screen, (33, 103, 126), (50, 113), (378, 113), 1)
        pygame.draw.line(
            self.screen,
            (64, 194, 211),
            (50, 113),
            (50 + int(shown_score % 1000 / 1000 * 328), 113),
            2,
        )

        draw_panel(self.screen, pygame.Rect(WIDTH - 238, 25, 208, 96), (5, 14, 29, 220))
        timer_color = RED if self.time_left <= 10 else CYAN
        draw_text(self.screen, self.small_font, "LOCKDOWN", MUTED, (WIDTH - 134, 40), "midtop")
        draw_text(self.screen, self.title_font, f"{math.ceil(self.time_left):02d}", timer_color, (WIDTH - 134, 56), "midtop")
        timer_width = int(166 * self.time_left / ROUND_TIME)
        pygame.draw.rect(self.screen, (25, 43, 58), (WIDTH - 217, 105, 166, 3), border_radius=2)
        if timer_width:
            pygame.draw.rect(self.screen, timer_color, (WIDTH - 217, 105, timer_width, 3), border_radius=2)

        draw_text(
            self.screen,
            self.small_font,
            "W A S D  /  ARROWS     MOVE     •     ESC  EXIT",
            MUTED,
            (WIDTH / 2, HEIGHT - 24),
            "midbottom",
        )

    def draw_grid(self):
        offset = int(self.scene_time * 13) % 48
        grid = self.grid_surface
        grid.fill((0, 0, 0, 0))
        for x in range(-48 + offset, WIDTH, 48):
            pygame.draw.line(grid, (*GRID, 92), (x, 0), (x, HEIGHT), 1)
        for y in range(-48 + offset, HEIGHT, 48):
            pygame.draw.line(grid, (28, 54, 82, 92), (0, y), (WIDTH, y), 1)

        scan_y = int((self.scene_time * 35) % HEIGHT)
        pygame.draw.line(grid, (30, 159, 184, 35), (22, scan_y), (WIDTH - 22, scan_y), 2)
        self.screen.blit(grid, (0, 0))
        self.screen.blit(self.scanline_surface, (0, 0))

    def draw_title_screen(self):
        self.screen.blit(self.background, (0, 0))
        self.draw_grid()
        for particle in self.ambient_particles:
            particle.draw(self.screen)

        draw_panel(
            self.screen,
            pygame.Rect(246, 164, 788, 386),
            (5, 12, 26, 205),
        )
        draw_text(
            self.screen,
            self.small_font,
            "N A N O   S Y S T E M S   / /   OFFLINE",
            MUTED,
            (WIDTH // 2, 205),
            "midtop",
        )

        flicker = 0.88 + 0.12 * math.sin(self.scene_time * 5.2)
        title_color = (
            int(CYAN[0] * flicker),
            int(CYAN[1] * flicker),
            int(CYAN[2] * flicker),
        )
        draw_text(
            self.screen,
            self.logo_font,
            "NANO ESCAPE + SIGNAL",
            title_color,
            (WIDTH // 2, 270),
            "midtop",
        )
        pygame.draw.line(self.screen, (33, 136, 157), (389, 351), (891, 351), 1)
        draw_text(
            self.screen,
            self.font,
            "A SURVIVAL PROTOCOL",
            WHITE,
            (WIDTH // 2, 379),
            "midtop",
        )
        draw_text(
            self.screen,
            self.small_font,
            "COLLECT ENERGY  //  EVADE HOSTILE UNITS  //  HOLD FOR 60 SECONDS",
            MUTED,
            (WIDTH // 2, 416),
            "midtop",
        )

        prompt_alpha = int(150 + (math.sin(self.scene_time * 3.2) + 1) * 52)
        prompt_color = tuple(channel * prompt_alpha // 255 for channel in CYAN)
        draw_text(
            self.screen,
            self.font,
            "PRESS ENTER TO START",
            prompt_color,
            (WIDTH // 2, 478),
            "midtop",
        )
        draw_text(
            self.screen,
            self.small_font,
            "WASD / ARROWS  MOVE                         ESC  EXIT",
            MUTED,
            (WIDTH // 2, HEIGHT - 42),
            "midbottom",
        )
        self.screen.blit(self.vignette, (0, 0))

    def draw_countdown(self):
        self.draw_world()
        if self.fade_mode == "none":
            step = min(3, int(self.countdown_elapsed / 0.8))
            label = ("3", "2", "1", "GO")[step]
            color = CYAN if label == "GO" else WHITE
            scale = 1.0 + 0.08 * math.sin(self.scene_time * 7)
            image = self.countdown_font.render(label, True, color)
            if label == "GO":
                image = self.title_font.render(label, True, color)
            dimensions = (
                max(1, int(image.get_width() * scale)),
                max(1, int(image.get_height() * scale)),
            )
            image = pygame.transform.smoothscale(image, dimensions)
            draw_panel(
                self.screen,
                pygame.Rect(WIDTH // 2 - 170, HEIGHT // 2 - 130, 340, 260),
                (4, 12, 26, 220),
                border=color,
            )
            self.screen.blit(image, image.get_rect(center=(WIDTH // 2, HEIGHT // 2)))

    def draw_ending_sequence(self):
        self.screen.fill((3, 7, 16))
        self.draw_grid()
        for particle in self.terminal_particles:
            particle.draw(self.screen)

        progress = min(1.0, self.terminal_elapsed / self.terminal_progress_duration)
        eased_progress = 1.0 - (1.0 - progress) ** 2.2
        interface_flicker = 0.84 + 0.16 * math.sin(self.scene_time * 9)
        accent = (
            int(CYAN[0] * interface_flicker),
            int(CYAN[1] * interface_flicker),
            int(CYAN[2] * interface_flicker),
        )

        draw_panel(
            self.screen,
            pygame.Rect(190, 105, 900, 510),
            (4, 12, 25, 235),
            border=accent,
        )
        draw_text(
            self.screen,
            self.small_font,
            "NANO SYSTEMS  /  ROOT ACCESS TERMINAL",
            MUTED,
            (228, 132),
        )
        draw_text(
            self.screen,
            self.small_font,
            "SECURE LINK  //  ENCRYPTION: ACTIVE",
            accent,
            (1052, 132),
            "topright",
        )
        pygame.draw.line(self.screen, (30, 83, 103), (228, 161), (1052, 161), 1)

        glitch_phase = int(self.terminal_elapsed * 13) % 17
        glitching = glitch_phase in (0, 1, 2)
        message = "System breach accessing mainframe."
        if glitching:
            glitch_x = math.sin(self.scene_time * 83) * 4
            draw_text(
                self.screen,
                self.terminal_text_font,
                message,
                RED,
                (WIDTH // 2 + int(glitch_x) - 2, 221),
                "midtop",
            )
            draw_text(
                self.screen,
                self.terminal_text_font,
                message,
                CYAN,
                (WIDTH // 2 - int(glitch_x) + 2, 221),
                "midtop",
            )
        else:
            draw_text(
                self.screen,
                self.terminal_text_font,
                message,
                WHITE,
                (WIDTH // 2, 221),
                "midtop",
            )

        log_lines = (
            ">> establishing encrypted uplink",
            ">> bypassing perimeter firewall",
            ">> decrypting mainframe handshake",
        )
        log_count = min(3, int(self.terminal_elapsed * 0.68) + 1)
        for index in range(log_count):
            line_color = (91, 160, 180) if index < log_count - 1 else accent
            draw_text(
                self.screen,
                self.terminal_particle_font,
                log_lines[index],
                line_color,
                (278, 307 + index * 30),
            )
        status = "ACCESS IN PROGRESS" if progress < 1.0 else "ACCESS GRANTED"
        draw_text(
            self.screen,
            self.small_font,
            status,
            accent,
            (1002, 367),
            "topright",
        )

        bar_rect = pygame.Rect(278, 416, 724, 18)
        pygame.draw.rect(self.screen, (12, 30, 43), bar_rect, border_radius=4)
        pygame.draw.rect(self.screen, (33, 77, 96), bar_rect, width=1, border_radius=4)
        fill_width = int((bar_rect.width - 4) * eased_progress)
        if fill_width > 0:
            fill_rect = pygame.Rect(bar_rect.x + 2, bar_rect.y + 2, fill_width, bar_rect.height - 4)
            pygame.draw.rect(self.screen, accent, fill_rect, border_radius=3)
            pygame.draw.rect(
                self.screen,
                (193, 255, 255),
                (fill_rect.right - min(12, fill_rect.width), fill_rect.y, min(12, fill_rect.width), fill_rect.height),
                border_radius=3,
            )

        percent = int(eased_progress * 100)
        draw_text(
            self.screen,
            self.font,
            f"{percent:3d} %",
            WHITE,
            (WIDTH // 2, 455),
            "midtop",
        )

        if progress >= 1.0:
            complete_alpha = min(255, int((self.terminal_elapsed - self.terminal_progress_duration) * 700))
            self.terminal_completed_text.set_alpha(complete_alpha)
            completed_rect = self.terminal_completed_text.get_rect(center=(WIDTH // 2, 520))
            self.screen.blit(self.terminal_completed_text, completed_rect)

        if self.terminal_elapsed >= self.terminal_reveal_time:
            score_text = self.font.render(f"FINAL SCORE   {self.score:06d}", True, GOLD)
            prompt_alpha = int(165 + (math.sin(self.scene_time * 3) + 1) * 45)
            prompt_text = self.small_font.render("PRESS ENTER TO PLAY AGAIN", True, CYAN)
            prompt_text.set_alpha(prompt_alpha)
            self.screen.blit(score_text, score_text.get_rect(center=(WIDTH // 2, 568)))
            self.screen.blit(prompt_text, prompt_text.get_rect(center=(WIDTH // 2, 592)))

        self.screen.blit(self.vignette, (0, 0))

        distortion_phase = self.scene_time % 3.2
        if distortion_phase < 0.09:
            frame = self.screen.copy()
            for index in range(3):
                band_y = 170 + ((index * 137 + int(self.scene_time * 47)) % 390)
                band_height = 3 + index
                band = frame.subsurface(pygame.Rect(0, band_y, WIDTH, band_height))
                self.screen.blit(band, (int(math.sin(self.scene_time * 71 + index) * 9), band_y))

        brightness = min(1.0, self.terminal_elapsed / self.terminal_progress_duration)
        if brightness > 0:
            overlay_alpha = int(brightness * 22)
            self.flash_surface.fill((130, 210, 220, overlay_alpha))
            self.screen.blit(self.flash_surface, (0, 0))

        flash_progress = max(
            0.0,
            1.0 - abs(self.terminal_elapsed - 6.12) / 0.28,
        )
        if flash_progress > 0:
            white_alpha = int(255 * flash_progress ** 1.5)
            self.flash_surface.fill((255, 255, 255, white_alpha))
            self.screen.blit(self.flash_surface, (0, 0))

    def draw_world(self, terminal_state=None):
        self.screen.blit(self.background, (0, 0))
        self.draw_grid()
        for particle in self.ambient_particles:
            particle.draw(self.screen)
        for orb in self.orbs:
            orb.draw(self.screen)
        for pulse in self.radial_pulses:
            pulse.draw(self.screen)
        for drone in self.drones:
            drone.draw(self.screen)
        self.player.draw(self.screen)
        for particle in self.particles:
            particle.draw(self.screen)
        self.screen.blit(self.vignette, (0, 0))
        self.draw_hud()
        overlay_state = terminal_state or self.state
        if overlay_state == "game_over" or overlay_state == "victory":
            self.draw_overlay(overlay_state)

    def draw_overlay(self, state=None):
        self.screen.blit(self.overlay_shade, (0, 0))

        if (state or self.state) == "game_over":
            heading = "SIGNAL LOST"
            detail = "A hunter drone breached your perimeter."
            heading_color = RED
        else:
            heading = "ESCAPE COMPLETE"
            detail = "You survived the lockdown."
            heading_color = CYAN

        draw_panel(self.screen, pygame.Rect(340, 220, 600, 275), (9, 17, 32, 245), heading_color)
        draw_text(self.screen, self.state_font, heading, heading_color, (640, 275), "midtop")
        draw_text(self.screen, self.font, detail, WHITE, (640, 347), "midtop")
        draw_text(self.screen, self.font, f"FINAL SCORE   {self.score:05d}", GOLD, (640, 393), "midtop")
        draw_text(self.screen, self.small_font, "PRESS ENTER TO RUN AGAIN   //   ESC TO EXIT", MUTED, (640, 453), "midtop")

    def draw(self):
        if self.state == "title" or (
            self.state == "transition_out" and self.transition_from == "title"
        ):
            self.draw_title_screen()
        elif self.state == "countdown":
            self.draw_countdown()
        elif self.state == "ending" or (
            self.state == "transition_out" and self.transition_from == "ending"
        ):
            self.draw_ending_sequence()
        else:
            transition_state = (
                self.transition_from
                if self.state == "transition_out" and self.transition_from in ("game_over", "victory")
                else None
            )
            self.draw_world(transition_state)

        if self.state not in ("title", "transition_out", "countdown", "ending"):
            self.draw_screen_effects()

        if WEB_BUILD:
            self.draw_touch_controls()

        if self.fade_alpha > 0:
            progress = min(1.0, max(0.0, self.fade_alpha / 255))
            alpha = int(255 * progress * progress * (3 - 2 * progress))
            self.fade_surface.fill((0, 0, 0))
            self.fade_surface.set_alpha(alpha)
            self.screen.blit(self.fade_surface, (0, 0))

    def draw_touch_controls(self):
        controls = self.touch_controls_surface
        controls.fill((0, 0, 0, 0))
        buttons = (
            ((112, HEIGHT - 158), "^", "up"),
            ((64, HEIGHT - 108), "<", "left"),
            ((160, HEIGHT - 108), ">", "right"),
            ((112, HEIGHT - 58), "v", "down"),
        )
        for center, label, action in buttons:
            active = action in self.touch_fingers.values() or action == self.mouse_touch_action
            fill = (45, 232, 255, 112) if active else (9, 24, 40, 176)
            pygame.draw.circle(controls, fill, center, 40)
            pygame.draw.circle(controls, (45, 232, 255, 190), center, 40, width=2)
            draw_text(controls, self.font, label, WHITE, center, "center")

        if self.can_start():
            label = "TAP TO START" if self.state == "title" else "TAP TO RESTART"
            button = pygame.Rect(WIDTH - 282, HEIGHT - 112, 252, 76)
            pygame.draw.rect(controls, (9, 24, 40, 196), button, border_radius=12)
            pygame.draw.rect(controls, (*CYAN, 190), button, width=2, border_radius=12)
            draw_text(controls, self.small_font, label, WHITE, button.center, "center")
        self.screen.blit(controls, (0, 0))

    def can_start(self):
        return self.state in ("title", "game_over", "victory") or (
            self.state == "ending"
            and self.terminal_elapsed >= self.terminal_reveal_time
        )

    def start_transition(self):
        self.transition_from = self.state
        self.state = "transition_out"
        self.fade_alpha = 0
        self.fade_mode = "out"

    @staticmethod
    def touch_action_at(position):
        buttons = (
            ((112, HEIGHT - 158), "up"),
            ((64, HEIGHT - 108), "left"),
            ((160, HEIGHT - 108), "right"),
            ((112, HEIGHT - 58), "down"),
        )
        center, action = min(
            buttons,
            key=lambda button: pygame.Vector2(position).distance_squared_to(button[0]),
        )
        if pygame.Vector2(position).distance_squared_to(center) <= 40 ** 2:
            return action
        return None

    def touch_direction(self):
        actions = set(self.touch_fingers.values())
        if self.mouse_touch_action is not None:
            actions.add(self.mouse_touch_action)
        return (
            int("right" in actions) - int("left" in actions),
            int("down" in actions) - int("up" in actions),
        )

    def draw_screen_effects(self):
        if self.camera_shake_time > 0:
            elapsed = 0.46 - self.camera_shake_time
            strength = self.camera_shake_strength * (self.camera_shake_time / 0.46) ** 1.7
            offset = (
                round(math.sin(elapsed * 74) * strength),
                round(math.sin(elapsed * 91 + 0.8) * strength * 0.72),
            )
            frame = self.screen.copy()
            self.screen.fill(BACKGROUND)
            self.screen.blit(frame, offset)

        if self.screen_flash_time > 0:
            progress = self.screen_flash_time / 0.24
            alpha = int(160 * progress * progress)
            self.flash_surface.fill((255, 45, 60, alpha))
            self.screen.blit(self.flash_surface, (0, 0))

        if self.impact_cue_time > 0:
            progress = self.impact_cue_time / 1.15
            alpha = int(255 * min(1.0, progress * 2.5))
            self.impact_cue.set_alpha(alpha)
            cue_rect = self.impact_cue.get_rect(center=(WIDTH // 2, 184))
            self.screen.blit(self.impact_cue, cue_rect)
            line_alpha = int(150 * progress)
            self.cue_line.fill((0, 0, 0, 0))
            pygame.draw.line(self.cue_line, (255, 55, 78, line_alpha), (0, 1), (430, 1), 2)
            self.screen.blit(self.cue_line, self.cue_line.get_rect(center=(WIDTH // 2, 218)))

    def render(self):
        window = self.window
        target_size = window.get_size()
        if target_size == self.screen.get_size():
            window.blit(self.screen, (0, 0))
            return

        scale = min(target_size[0] / self.screen.get_width(), target_size[1] / self.screen.get_height())
        fit_width = max(1, int(round(self.screen.get_width() * scale)))
        fit_height = max(1, int(round(self.screen.get_height() * scale)))
        offset_x = max(0, (target_size[0] - fit_width) // 2)
        offset_y = max(0, (target_size[1] - fit_height) // 2)
        scaled = pygame.transform.smoothscale(self.screen, (fit_width, fit_height))
        window.fill(BACKGROUND)
        window.blit(scaled, (offset_x, offset_y))

    async def run(self):
        running = True
        while running:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.VIDEORESIZE and not WEB_BUILD:
                    self.window = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_RETURN and self.can_start():
                        self.start_transition()
                elif WEB_BUILD and event.type == pygame.FINGERDOWN:
                    position = (event.x * WIDTH, event.y * HEIGHT)
                    if self.can_start() and position[0] > WIDTH * 0.55 and position[1] > HEIGHT * 0.55:
                        self.start_transition()
                    else:
                        self.touch_fingers[event.finger_id] = self.touch_action_at(position)
                elif WEB_BUILD and event.type == pygame.FINGERMOTION:
                    position = (event.x * WIDTH, event.y * HEIGHT)
                    self.touch_fingers[event.finger_id] = self.touch_action_at(position)
                elif WEB_BUILD and event.type == pygame.FINGERUP:
                    self.touch_fingers.pop(event.finger_id, None)
                elif WEB_BUILD and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self.can_start() and event.pos[0] > WIDTH * 0.55 and event.pos[1] > HEIGHT * 0.55:
                        self.start_transition()
                    else:
                        self.mouse_touch_action = self.touch_action_at(event.pos)
                elif WEB_BUILD and event.type == pygame.MOUSEMOTION and self.mouse_touch_action is not None:
                    self.mouse_touch_action = self.touch_action_at(event.pos)
                elif WEB_BUILD and event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    self.mouse_touch_action = None

            self.touch_fingers = {
                finger_id: action
                for finger_id, action in self.touch_fingers.items()
                if action is not None
            }
            self.update(dt)
            self.draw()
            self.render()
            pygame.display.flip()
            await asyncio.sleep(0)


async def main():
    pygame.mixer.pre_init(AUDIO_SAMPLE_RATE, -16, 1, 512)
    pygame.init()
    if pygame.mixer.get_init() is None:
        try:
            pygame.mixer.init(AUDIO_SAMPLE_RATE, -16, 1, 512)
        except pygame.error as error:
            print(f"Audio unavailable; continuing without sound: {error}", file=sys.stderr)
    pygame.display.set_caption("NANO ESCAPE // Cybernetic Lockdown")
    window = pygame.display.set_mode((WIDTH, HEIGHT), 0 if WEB_BUILD else pygame.RESIZABLE)
    screen = pygame.Surface((WIDTH, HEIGHT))
    game = NanoEscapeGame(screen)
    game.window = window
    await game.run()
    if not WEB_BUILD:
        pygame.quit()


if __name__ == "__main__":
    asyncio.run(main())
