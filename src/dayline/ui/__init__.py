"""Native GTK 4 agenda. Import only from interactive commands: importing loads GTK."""

import ctypes

# gtk4-layer-shell must load before GTK connects to Wayland.
ctypes.CDLL("libgtk4-layer-shell.so.0")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gtk4LayerShell", "1.0")
gi.require_version("GLibUnix", "2.0")
