import pygame
from wayland import server
import time
import numpy
import mmap
import sys
from xkbcommon import xkb
import os


class Display(server.Display):
    def __init__(self):
        self.screen = pygame.display.set_mode((800, 600))
        self.windows = []
        self.start_time = time.time()
        self.cursor = None
        self.mx = 0
        self.my = 0
        self.moving = None
        super().__init__(Output(self), Compositor(self), Subcompositor(self), Shm(self), XdgShellV6(self),
                         XdgShellV5(self), Seat(self), Shell(self))
        print(self.path)
        self.next_serial = 0

    def serial(self):
        self.next_serial += 1
        return self.next_serial


class Compositor(object):
    name = "wl_compositor"
    version = 1
    proxy = server.CompositorProxy

    def __init__(self, display):
        self.display = display
        self.surfaces = self.display.windows
        self.last_rectangles = [(0, 0, self.display.screen.get_width(), self.display.screen.get_height())]

    def create_surface(self, proxy, obj_id):
        surface = Surface(proxy.display, obj_id, self)
        self.surfaces.append(surface)
        proxy.surfaces.append(surface)
        proxy.display.objects[obj_id] = surface

    def create_region(self, proxy, obj_id):
        proxy.display.objects[obj_id] = Region(proxy.display, obj_id)

    def setup(self, proxy):
        proxy.surfaces = []

    def update(self):
        rectangles = []
        self.display.screen.fill((16, 32, 96))
        for c in self.surfaces:
            if c.surface is not None:
                rectangles.append(pygame.draw.rect(self.display.screen, (255, 0, 0), self.display.screen.blit(c.surface, (c.x, c.y)), 1))
            if c.frame is not None:
                c.frame.send_done(int((time.time()-self.display.start_time)*1000))
        if self.display.cursor is not None:
            rectangles.append(self.display.screen.blit(self.display.cursor.surface,
                                                       (self.display.cursor.x+self.display.mx-self.display.hotspot_x,
                                                        self.display.cursor.y+self.display.my-self.display.hotspot_y)))
        pygame.display.update(self.last_rectangles + rectangles)
        self.last_rectangles = rectangles

    def destroy(self, proxy):
        for c in proxy.surfaces:
            if c in self.surfaces:
                self.surfaces.remove(c)


class Surface(server.Surface):
    def __init__(self, display, obj_id, compositor):
        super().__init__(display, obj_id)
        self.frame = None
        self.pending_buffer = None
        self.pending_x = 0
        self.pending_y = 0
        self.buffer = None
        self.x = 0
        self.y = 0
        self.pending_damage = Region(display, -1)
        self.pending_opaque_region = None
        self.pending_input_region = None
        self.opaque_region = None
        self.input_region = None
        self.surface = None
        self.compositor = compositor
        self.scale = 1
        self.transform = None

    def handle_commit(self):
        if (self.pending_buffer is not None and
                (self.buffer is None or
                 self.buffer.width != self.pending_buffer.width or
                 self.buffer.height != self.pending_buffer.height or
                 self.pending_x != 0 or self.pending_y != 0)):
            surface = pygame.Surface((self.pending_buffer.width, self.pending_buffer.height), pygame.SRCALPHA)
            if self.surface is not None:
                surface.blit(self.surface, (self.pending_x, self.pending_y))
            self.surface = surface
        self.buffer = self.pending_buffer
        self.pending_buffer = None
        self.x += self.pending_x
        self.y += self.pending_y
        self.pending_x = 0
        self.pending_y = 0
        if self.buffer is not None:
            pixels = pygame.surfarray.pixels3d(self.surface)
            alpha = pygame.surfarray.pixels_alpha(self.surface)
            for r in self.pending_damage.rectangles:
                pixels[r[0]:r[0]+r[2], r[1]:r[1]+r[3], ::] = self.buffer.pixels[r[0]:r[0]+r[2], r[1]:r[1]+r[3], 2::-1]
                if self.buffer.format == server.ShmProxy.ARGB8888:
                    alpha[r[0]:r[0] + r[2], r[1]:r[1] + r[3]] = self.buffer.pixels[r[0]:r[0] + r[2], r[1]:r[1] + r[3], 3]
                else:
                    alpha[r[0]:r[0] + r[2], r[1]:r[1] + r[3]] = 255
            self.buffer.send_release()
        self.pending_damage = Region(self.display, -1)

    def handle_frame(self, callback):
        self.frame = server.Callback(self.display, callback)
        self.display.objects[callback] = self.frame

    def handle_attach(self, buffer, x, y):
        self.pending_buffer = buffer
        self.pending_x = x
        self.pending_y = y

    def handle_damage(self, x, y, width, height):
        self.pending_damage.handle_add(x, y, width, height)

    def handle_set_opaque_region(self, region):
        self.pending_opaque_region = region

    def handle_set_input_region(self, region):
        self.pending_input_region = region

    def handle_destroy(self):
        if self in self.compositor.surfaces:
            self.compositor.surfaces.remove(self)

    def handle_set_buffer_scale(self, scale):
        self.scale = scale

    def handle_set_buffer_transform(self, transform):
        self.transform = transform


class Region(server.Region):
    def __init__(self, display, obj_id):
        super().__init__(display, obj_id)
        self.rectangles = []

    def handle_add(self, x, y, width, height):
        self.rectangles.append((x, y, width, height))

    def handle_destroy(self):
        self.display.objects[self] = None
        self.display.send_delete_id(self)


class Output(object):
    name = "wl_output"
    version = 1
    proxy = server.OutputProxy

    def __init__(self, display):
        self.display = display

    def setup(self, proxy):
        proxy.width = self.display.screen.get_width()
        proxy.height = self.display.screen.get_height()
        proxy.send_geometry(self.display.screen.get_width(), self.display.screen.get_height(), self.display.screen.get_width(), self.display.screen.get_height(), proxy.UNKNOWN, "None", "None", proxy.NORMAL)

    def update(self):
        pass

    def destroy(self, proxy):
        pass


class Subcompositor(object):
    name = "wl_subcompositor"
    version = 1
    proxy = server.SubcompositorProxy

    def __init__(self, display):
        self.display = display

    def setup(self, proxy):
        pass

    def update(self):
        pass

    def destroy(self, proxy):
        pass


class Shm(object):
    name = "wl_shm"
    version = 1
    proxy = server.ShmProxy

    def __init__(self, display):
        self.display = display

    def create_pool(self, proxy, id, fd, size):
        pool = ShmPool(proxy.display, id, fd, size)
        proxy.display.objects[id] = pool

    def setup(self, proxy):
        proxy.send_format(proxy.ARGB8888)
        proxy.send_format(proxy.XRGB8888)

    def update(self):
        pass

    def destroy(self, proxy):
        pass


class ShmPool(server.ShmPool):
    def __init__(self, display, obj_id, fd, size):
        super().__init__(display, obj_id)
        self.fd = fd
        self.size = size
        self.data = mmap.mmap(fd, size)
        self.dead = False
        self.buffers = []

    def handle_resize(self, size):
        self.data = mmap.mmap(self.fd, size)
        self.size = size

    def handle_create_buffer(self, id, offset, width, height, stride, format):
        buffer = Buffer(self.display, id, self, self.data, offset, width, height, stride, format)
        self.buffers.append(buffer)
        self.display.objects[id] = buffer

    def handle_destroy(self):
        self.dead = True
        if len(self.buffers) == 0:
            self.data.close()

    def close(self, buffer):
        self.buffers.remove(buffer)
        if self.dead and len(self.buffers) == 0:
            self.data.close()


class Buffer(server.Buffer):
    def __init__(self, display, obj_id, pool, data, offset, width, height, stride, format):
        super().__init__(display, obj_id)
        self.pool = pool
        self.pool.buffers.append(self)
        data = numpy.ndarray(buffer=data, offset=offset, shape=(height, width, 4), dtype=numpy.uint8)
        self.pixels = numpy.swapaxes(data, 0, 1)
        self.width = width
        self.height = height
        self.stride = stride
        self.format = format

    def handle_destroy(self):
        self.pool.close(self)


class XdgShellV6(object):
    name = "zxdg_shell_v6"
    version = 1
    proxy = server.ZxdgShellV6Proxy

    def __init__(self, display):
        self.display = display

    def get_xdg_surface(self, proxy, obj_id, surface):
        xdg_surface = XdgSurfaceV6(proxy.display, obj_id, surface, self)
        proxy.display.objects[obj_id] = xdg_surface

    def create_positioner(self, proxy, obj_id):
        positioner = XdgPositionerV6(proxy.display, obj_id)
        proxy.display.objects[obj_id] = positioner

    def setup(self, proxy):
        pass

    def update(self):
        pass

    def destroy(self, proxy):
        pass


class XdgSurfaceV6(server.ZxdgSurfaceV6):
    def __init__(self, display, obj_id, surface, shell):
        super().__init__(display, obj_id)
        self.surface = surface
        self.shell = shell
        self.geometry = None

    def handle_ack_configure(self, serial):
        pass

    def handle_get_toplevel(self, id):
        xdg_surface = XdgToplevelV6(self.display, id, self, self.shell)
        self.display.objects[id] = xdg_surface

    def handle_get_popup(self, id, parent, positioner):
        self.display.objects[id] = XdgPopupV6(self.display, id, self, parent, positioner)

    def handle_set_window_geometry(self, x, y, width, height):
        self.geometry = (x, y, width, height)

    def handle_destroy(self):
        pass


class XdgPositionerV6(server.ZxdgPositionerV6):
    def __init__(self, display, obj_id):
        super().__init__(display, obj_id)
        self.width = 0
        self.height = 0
        self.anchor_x = 0
        self.anchor_y = 0
        self.anchor_width = 0
        self.anchor_height = 0
        self.anchor = None
        self.gravity = None

    def handle_destroy(self):
        pass

    def handle_set_size(self, width, height):
        self.width = width
        self.height = height

    def handle_set_anchor_rect(self, x, y, width, height):
        self.anchor_x = x
        self.anchor_y = y
        self.anchor_width = width
        self.anchor_height = height

    def handle_set_anchor(self, anchor):
        self.anchor = anchor

    def handle_set_gravity(self, gravity):
        self.gravity = gravity


class XdgToplevelV6(server.ZxdgToplevelV6):
    def __init__(self, display, obj_id, surface, shell):
        super().__init__(display, obj_id)
        self.surface = surface
        self.app_id = ""
        self.title = ""
        self.send_configure(0, 0, (self.ACTIVATED,))
        self.surface.send_configure(0)
        self.shell = shell

    def handle_set_app_id(self, app_id):
        self.app_id = app_id

    def handle_set_title(self, title):
        self.title = title

    def handle_destroy(self):
        pass

    def handle_move(self, seat, serial):
        self.shell.display.moving = self.surface.surface


class XdgPopupV6(server.ZxdgPopupV6):
    def __init__(self, display, obj_id, surface, parent, positioner):
        super().__init__(display, obj_id)
        self.surface = surface
        self.parent = parent
        base_x = self.parent.surface.x
        base_y = self.parent.surface.y
        base_x += positioner.anchor_x
        base_y += positioner.anchor_y
        if positioner.anchor & positioner.BOTTOM:
            base_y += positioner.anchor_height
        if positioner.anchor & positioner.RIGHT:
            base_x += positioner.anchor_width
        if positioner.gravity & positioner.TOP:
            base_y -= positioner.height
        if positioner.gravity & positioner.LEFT:
            base_x -= positioner.width
        self.surface.surface.x = base_x
        self.surface.surface.y = base_y

    def handle_destroy(self):
        pass  # self.surface.surface.destroy()


class XdgShellV5(object):
    name = "xdg_shell"
    version = 1
    proxy = server.XdgShellProxy

    def __init__(self, display):
        self.display = display

    def use_unstable_version(self, proxy, version):
        proxy.version = version
        if version != 5:
            proxy.display.connection.close()

    def get_xdg_surface(self, proxy, obj_id, surface):
        xdg_surface = XdgSurfaceV5(proxy.display, obj_id, surface, self)
        proxy.display.objects[obj_id] = xdg_surface

    def get_xdg_popup(self, proxy, obj_id, surface, parent, seat, serial, x, y):
        surface.x = parent.x + x
        surface.y = parent.y + y
        proxy.display.objects[obj_id] = XdgPopupV5(proxy.display, obj_id, surface, parent)

    def setup(self, proxy):
        pass

    def update(self):
        pass

    def destroy(self, proxy):
        pass


class XdgSurfaceV5(server.XdgSurface):
    def __init__(self, display, obj_id, surface, shell):
        super().__init__(display, obj_id)
        self.surface = surface
        self.send_configure(0, 0, [self.ACTIVATED], 0)
        self.shell = shell
        self.parent = None
        self.geometry = None
        self.old_x = 0
        self.old_y = 0
        self.old_width = 0
        self.old_height = 0
        self.title = ""
        self.app_id = ""

    def handle_destroy(self):
        pass

    def handle_resize(self, seat, serial, edges):
        pass

    def handle_move(self, seat, serial):
        self.shell.display.moving = self.surface

    def handle_set_parent(self, parent):
        self.parent = parent

    def handle_set_window_geometry(self, x, y, width, height):
        self.geometry = x, y, width, height

    def handle_ack_configure(self, serial):
        pass

    def handle_set_maximized(self):
        self.old_x = self.surface.x
        self.old_y = self.surface.y
        self.old_width = self.surface.buffer.width
        self.old_height = self.surface.buffer.height
        self.send_configure(self.shell.display.screen.get_width(), self.shell.display.screen.get_height(), (self.MAXIMIZED, self.ACTIVATED), 0)
        self.surface.x = 0
        self.surface.y = 0

    def handle_unset_maximized(self):
        self.send_configure(self.old_width, self.old_height, (self.ACTIVATED,), 0)
        self.surface.x = self.old_x
        self.surface.y = self.old_y

    def handle_set_minimized(self):
        pass

    def handle_set_title(self, title):
        self.title = title

    def handle_set_app_id(self, app_id):
        self.app_id = app_id


class XdgPopupV5(server.XdgPopup):
    def __init__(self, display, obj_id, surface, parent):
        super().__init__(display, obj_id)
        self.surface = surface
        self.parent = parent

    def handle_destroy(self):
        pass


class Seat(object):
    name = "wl_seat"
    version = 1
    proxy = server.SeatProxy

    def __init__(self, display):
        self.display = display

    def setup(self, proxy):
        proxy.send_capabilities(proxy.POINTER + proxy.KEYBOARD)
        # proxy.send_name("Bob")

    def update(self):
        pass

    def destroy(self, proxy):
        pass

    def get_pointer(self, proxy, obj_id):
        proxy.display.pointer = Pointer(proxy.display, obj_id, self)
        proxy.display.objects[obj_id] = proxy.display.pointer

    def get_keyboard(self, proxy, obj_id):
        proxy.display.keyboard = Keyboard(proxy.display, obj_id, self)
        proxy.display.objects[obj_id] = proxy.display.keyboard


class Pointer(server.Pointer):
    def __init__(self, display, obj_id, seat):
        super().__init__(display, obj_id)
        self.seat = seat

    def handle_release(self):
        del self.display.pointer

    def handle_set_cursor(self, serial, surface, hotspot_x, hotspot_y):
        self.seat.display.cursor = surface
        self.seat.display.hotspot_x = hotspot_x
        self.seat.display.hotspot_y = hotspot_y


class Keyboard(server.Keyboard):
    keymap = None

    def __init__(self, display, obj_id, seat):
        super().__init__(display, obj_id)
        if self.keymap is None:
            ctx = xkb.Context()
            Keyboard.keymap = ctx.keymap_new_from_names()
        keymap = self.keymap.get_as_bytes()
        self.fd = os.open("/tmp", os.O_RDWR | os.O_TMPFILE)
        os.set_inheritable(self.fd, True)
        written = 0
        while written < len(keymap):
            written += os.write(self.fd, keymap[written:])
        self.send_keymap(self.XKB_V1, self.fd, len(keymap))
        # os.close(self.fd)
        self.seat = seat

    def handle_release(self):
        os.close(self.fd)
        del self.display.keyboard


class Shell(object):
    name = "wl_shell"
    version = 1
    proxy = server.ShellProxy

    def __init__(self, display):
        self.display = display

    def get_shell_surface(self, proxy, obj_id, surface):
        shell_surface = ShellSurface(proxy.display, obj_id, surface)
        proxy.display.objects[obj_id] = shell_surface

    def setup(self, proxy):
        pass

    def update(self):
        pass

    def destroy(self, proxy):
        pass


class ShellSurface(server.ShellSurface):
    def __init__(self, display, obj_id, surface):
        super().__init__(display, obj_id)
        self.surface = surface
        self.toplevel = False
        self.title = ""

    def handle_set_toplevel(self):
        self.toplevel = True

    def handle_set_maximized(self, output):
        self.send_configure(self.NONE, output.width, output.height)

    def handle_set_title(self, title):
        self.title = title


class DataDeviceManager(object):
    name = "wl_data_device_manager"
    version = 1
    proxy = server.DataDeviceManagerProxy

    def __init__(self, display):
        self.display = display

    def setup(self, proxy):
        pass

    def update(self):
        pass

    def destroy(self, proxy):
        pass


keys = {pygame.K_UP: 103, pygame.K_DOWN: 108, pygame.K_RIGHT: 106, pygame.K_LEFT: 105, pygame.K_SPACE: 57,
        pygame.K_PERIOD: 52, pygame.K_COMMA: 51, pygame.K_SLASH: 53, pygame.K_LSHIFT: 34, pygame.K_RSHIFT: 46,
        pygame.K_BACKSPACE: 6, pygame.K_RETURN: 24}

for key, code in zip("qwertyuiopasdfghjklzxcvbnm", range(16, 50)):
    keys[getattr(pygame, "K_"+key)] = code


def main():
    display = Display()
    buttons = [0, 272, 274, 273]
    try:
        last_time = 0.0
        last_button_down = 0, 0
        last_window = None
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    display.server.close()
                    sys.exit()
                elif event.type == pygame.MOUSEMOTION:
                    x, y = event.pos
                    display.mx = x
                    display.my = y
                    if display.moving is not None:
                        lx, ly = last_button_down
                        last_button_down = x, y
                        display.moving.x += x - lx
                        display.moving.y += y - ly
                        continue
                    elif last_window is not None:
                        if last_window.buffer is not None and hasattr(last_window.display, "pointer") and last_window.x <= x < last_window.x + last_window.buffer.width and last_window.y <= y < last_window.y + last_window.buffer.height:
                            last_window.display.pointer.send_motion(time.time()-display.start_time, (x-c.x)*256, (y-c.y)*256)
                            continue
                        elif hasattr(last_window.display, "pointer"):
                            last_window.display.pointer.send_leave(display.serial(), last_window)
                            last_window = None
                            # last_window.display.pointer.send_frame()
                    for c in display.windows:
                        if c.buffer is not None and hasattr(c.display, "pointer") and c.x <= x < c.x + c.buffer.width and c.y <= y < c.y + c.buffer.height:
                            # print("Detected Motion!")
                            last_window = c
                            c.display.pointer.send_enter(display.serial(), c, (x-c.x)*256, (y-c.y)*256)
                            c.display.pointer.send_motion(time.time()-display.start_time, (x-c.x)*256, (y-c.y)*256)
                            # c.display.pointer.send_frame()
                            break
                elif event.type == pygame.MOUSEBUTTONUP:
                    x, y = event.pos
                    display.moving = None
                    for c in display.windows:
                        if c.buffer is not None and hasattr(c.display, "pointer") and c.x <= x < c.x + c.buffer.width and c.y <= y < c.y + c.buffer.height:
                            # print("Detected Motion!")
                            c.display.pointer.send_button(display.serial(), time.time()-display.start_time, buttons[event.button], c.display.pointer.RELEASED)
                            break
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    x, y = event.pos
                    last_button_down = x, y
                    for c in display.windows:
                        if c.buffer is not None and hasattr(c.display, "pointer") and c.x <= x < c.x + c.buffer.width and c.y <= y < c.y + c.buffer.height:
                            # print("Detected Button!")
                            c.display.pointer.send_button(display.serial(), time.time()-display.start_time, buttons[event.button], c.display.pointer.PRESSED)
                elif event.type == pygame.KEYDOWN:
                    if last_window is not None and hasattr(last_window.display, "keyboard") and last_window.display.keyboard is not None:
                        last_window.display.keyboard.send_key(display.serial(), time.time()-display.start_time, keys[event.key], Keyboard.PRESSED)
                elif event.type == pygame.KEYUP:
                    if last_window is not None and hasattr(last_window.display, "keyboard") and last_window.display.keyboard is not None:
                        last_window.display.keyboard.send_key(display.serial(), time.time()-display.start_time, keys[event.key], Keyboard.RELEASED)
            display.handle_requests()
            if time.time() - last_time > 0.05:
                for o in display.global_objects:
                    o.update()
                last_time = time.time()
    finally:
        import os
        os.remove(display.path)


if __name__ == "__main__":
    main()
