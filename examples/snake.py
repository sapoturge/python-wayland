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
        self.pixels = None
        self.buffer = None
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
                self.quit()
                return
            if new_head[0] >= self.width:
                print("Collision")
                self.quit()
                return
            if new_head[0] < 0:
                print("Collision")
                self.quit()
                return
            if new_head[1] >= self.height:
                print("Collision")
                self.quit()
                return
            if new_head[1] < 0:
                print("Collision")
                self.quit()
                return
            self.snake.insert(0, new_head)
            if new_head == self.apple:
                self.set_apple_pos()
            else:
                self.snake = self.snake[:-1]
            self.pixels.fill(32)
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
            if keysym == "Right":
                self.direction = self.RIGHT
            elif keysym == "Left":
                self.direction = self.LEFT
            elif keysym == "Up":
                self.direction = self.UP
            elif keysym == "Down":
                self.direction = self.DOWN
            elif keysym == "Escape":
                self.quit()

    def setup_wayland(self):
        self.display = client.Display("wayland-0")
        compositor = self.display.globals["wl_compositor"]
        shell = self.display.globals["wl_shell"]
        seat = self.display.globals["wl_seat"]
        shm = self.display.globals["wl_shm"]
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
        if shm.XRGB8888 not in shm.availible:
            raise Exception("Shared Memory Format is unavailible")
        self.surface = compositor.create_surface()
        shell_surface = shell.get_shell_surface(self.surface)
        shell_surface.set_toplevel()
        self.display.roundtrip()
        path = tempfile.mktemp("dat", "win")
        self.data_file = open(path, "wb+")
        fd = self.data_file.fileno()
        pool = shm.create_pool(fd, self.width*self.height*400)
        self.buffer = pool.create_buffer(0, self.width*10, self.height*10, self.width*40, shm.XRGB8888)
        self.pixels = numpy.memmap(path, shape=(self.height*10, self.width*10, 4))
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

    def run_game(self):
        self.running = True
        self.redraw(100)
        while self.running:
            self.display.dispatch()


if __name__ == '__main__':
    s = Snake(40, 30)
    s.run_game()
