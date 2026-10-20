-- Dayline for Hyprland's Lua configuration. Replace DAYLINE with the absolute
-- path of the Dayline executable, for example /path/to/Dayline/.venv/bin/dayline.
-- Super+N stays with SwayNC; Super+A toggles the panel; Super+T toggles the widget.
local dayline = "DAYLINE"

hl.on("hyprland.start", function()
    hl.exec_cmd(dayline .. " ui")
end)

hl.bind("SUPER + A", hl.dsp.exec_cmd(dayline .. " ui toggle"))
hl.bind("SUPER + T", hl.dsp.exec_cmd(dayline .. " ui toggle-widget"))

-- Let the focus indicator follow the pointer while dragged instead of animating
-- each move. This also removes its fade when it appears or hides.
hl.layer_rule({
    name = "dayline-focus-no-anim",
    match = { namespace = "^dayline-focus$" },
    no_anim = true,
})
