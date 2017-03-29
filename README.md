# python-wayland
Pure-python implementation of the wayland protocol

## Client side
To create a wayland client, import `wayland.client`, then create a `Display`.
Core wayland global objects are bound automatically, and stored in `display.compositor`, `display.shell`, etc.

