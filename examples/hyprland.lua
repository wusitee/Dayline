-- Dayline for Hyprland's Lua configuration. Replace DAYLINE with the absolute
-- path of the Dayline executable, for example /path/to/Dayline/.venv/bin/dayline.
-- Super+N stays with SwayNC; Super+A toggles the agenda.
local dayline = "DAYLINE"

hl.on("hyprland.start", function()
    hl.exec_cmd(dayline .. " ui")
end)

hl.bind("SUPER + A", hl.dsp.exec_cmd(dayline .. " ui toggle"))
