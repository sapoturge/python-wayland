import random
import tempfile

import numpy

from wayland import client


class Snake(object):
    WHITE = (255, 255, 255, 255)
    BLACK = (0, 0, 0, 255)
    RED = (0, 0, 255, 255)
    GREEN = (0, 255, 0, 255)

    UP, DOWN, LEFT, RIGHT = 0, 1, 2, 3

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.display = None
        self.surface = None
        self.shell_surface = None
        self.pixels = None
        self.buffer = None
        self.pool = None
        self.fd = 0
        self.path = ""
        self.shm = None
        self.data_file = None
        self.setup_wayland()
        startx = random.randint(5, width-6)
        starty = random.randint(5, height-6)
        self.snake = [(startx, starty), (startx-1, starty), (startx-2, starty)]
        self.direction = self.RIGHT
        self.apple = None
        self.running = True
        self.set_apple_pos()
        self.last_time = 0

    def redraw(self, time):
        if time - self.last_time >= 1000 / 10:
            old_head = self.snake[0]
            if self.direction == self.RIGHT:
                new_head = old_head[0] + 1, old_head[1]
            elif self.direction == self.LEFT:
                new_head = old_head[0] - 1, old_head[1]
            elif self.direction == self.UP:
                new_head = old_head[0], old_head[1] - 1
            elif self.direction == self.DOWN:
                new_head = old_head[0], old_head[1] + 1
            else:
                self.quit()
                return
            if new_head in self.snake:
                print("Collision Self")
                self.quit()
                return
            if new_head[0] >= self.width:
                print("Collision Right")
                self.quit()
                return
            if new_head[0] < 0:
                print("Collision Left")
                self.quit()
                return
            if new_head[1] >= self.height:
                print("Collision Bottom")
                self.quit()
                return
            if new_head[1] < 0:
                print("Collision Top")
                self.quit()
                return
            self.snake.insert(0, new_head)
            if new_head == self.apple:
                self.set_apple_pos()
            else:
                self.snake = self.snake[:-1]
            self.pixels.fill(0)
            self.pixels[self.apple[1]*10:self.apple[1]*10+10, self.apple[0]*10:self.apple[0]*10+10] = self.RED
            for x, y in self.snake:
                self.pixels[y*10:y*10+10, x*10:x*10+10] = self.GREEN
            self.surface.attach(self.buffer, 0, 0)
            self.surface.damage(0, 0, self.width*10, self.height*10)
            self.last_time = time
        callback = self.surface.frame()
        callback.handle_done = self.redraw
        self.surface.commit()

    def handle_key(self, serial, time, keysym, state):
        if state == client.Keyboard.PRESSED:
            if keysym == "Right" and self.direction != self.LEFT:
                self.direction = self.RIGHT
            elif keysym == "Left" and self.direction != self.RIGHT:
                self.direction = self.LEFT
            elif keysym == "Up" and self.direction != self.DOWN:
                self.direction = self.UP
            elif keysym == "Down" and self.direction != self.UP:
                self.direction = self.DOWN
            elif keysym == "Escape":
                self.quit()
            else:
                print(keysym)

    def setup_wayland(self):
        self.display = client.Display("wayland-0")
        compositor = self.display.globals["wl_compositor"]
        shell = self.display.globals["zxdg_shell_v6"]
        seat = self.display.globals["wl_seat"]
        self.shm = self.display.globals["wl_shm"]
        output = self.display.globals["wl_output"]
        self.display.roundtrip()
        '''for obj in self.display.objects.values():
            if isinstance(obj, client.Seat):
                seat = obj
            elif isinstance(obj, client.Shm):
                shm = obj
            elif isinstance(obj, client.Compositor):
                compositor = obj
            elif isinstance(obj, client.Shell):
                shell = obj
        if compositor is None:
            raise Exception("No Compositor")
        elif shell is None:
            raise Exception("No Shell")
        elif seat is None:
            raise Exception("No Input seat")
        elif shm is None:
            raise Exception("Shared Memory is unavailible")'''
        if self.shm.ARGB8888 not in self.shm.available:
            raise Exception("Shared Memory Format is unavailible")
        self.surface = compositor.create_surface()
        self.surface.set_buffer_scale(1)
        self.shell_surface = shell.get_xdg_surface(self.surface)
        toplevel = self.shell_surface.get_toplevel()
        toplevel.set_maximized()
        toplevel.handle_configure = self.resize
        self.display.roundtrip()
        print(self.width, self.height)
        self.path = tempfile.mktemp("dat", "win")
        self.data_file = open(self.path, "wb+")
        self.fd = self.data_file.fileno()
        self.pool = self.shm.create_pool(self.fd, self.width*self.height*400)
        self.buffer = self.pool.create_buffer(0, self.width*10, self.height*10, self.width*40, self.shm.ARGB8888)
        self.pixels = numpy.memmap(self.path, shape=(self.height*10, self.width*10, 4))
        self.display.roundtrip()
        seat.handle_button = lambda *args: self.quit()
        seat.handle_key = self.handle_key

    def quit(self):
        self.buffer.destroy()
        self.surface.destroy()
        self.display.roundtrip()
        self.display.disconnect()
        del self.pixels
        self.running = False

    def set_apple_pos(self):
        self.apple = self.snake[0]
        while self.apple in self.snake:
            self.apple = (random.randint(0, self.width-1), random.randint(0, self.height-1))

    def resize(self, width, height, states):
        if width > 0:
            self.width = width//10
            self.height = height//10
            self.shell_surface.set_window_geometry(0, 0, width, height)
        # self.pool = self.shm.create_pool(self.fd, self.width * self.height * 4)
        # self.buffer = self.pool.create_buffer(0, self.width, self.height, self.width, self.shm.ARGB8888)
        # self.pixels = numpy.memmap(self.path, shape=(self.height, self.width, 4))
        # self.display.roundtrip()

    def run_game(self):
        self.running = True
        self.redraw(100)
        while self.running:
            self.display.dispatch()


if __name__ == '__main__':
    s = Snake(40, 30)
    s.run_game()
