# Resource measurements

The starting target is at most 100 MiB proportional set size (PSS) for Dayline
and its native-messaging broker with the widget visible, and less than 0.5% of
one CPU core averaged idle. Thunderbird is a required live-sync dependency and
is measured separately; its cost is not hidden in the Dayline target.

## Verified idle sample

Measured on 4 October 2026 with the compact widget visible and the full window
hidden. The matching live snapshot contained 74 items from five selected sources;
due-date reminders were enabled and explicit alarms were disabled.
Thunderbird/TbSync and SwayNC were running.
The session used Hyprland 0.56.2 at scale 2, Python 3.14.7, PyGObject 3.56.3,
GTK 4.22.5, gtk4-layer-shell 1.3.0, and Thunderbird 156.0.1 on x86-64 Linux
with an Intel Core i7-1165G7.

Thirteen PSS samples were taken over 60.48 seconds. CPU is the process group's
user/system CPU-time increase divided by elapsed wall time, expressed as a
percentage of one core.

| Process group | Processes | Mean PSS (MiB) | PSS range (MiB) | Idle CPU (% of one core) |
| --- | ---: | ---: | ---: | ---: |
| Dayline GTK application | 1 | 69.49 | 69.48–69.49 | 0.033 |
| Native-messaging broker | 1 | 4.89 | 4.89–4.89 | 0.000 |
| **Dayline and broker** | **2** | **74.38** | **74.37–74.38** | **0.033** |
| Thunderbird and content processes, excluding broker | 4 | 624.32 | 622.27–626.82 | 0.529 |

Both Dayline targets passed in this sample. This is an idle observation with one
account/session configuration, not a bound on startup, sync, editing, larger
calendars, or a visible full window. Thunderbird's background cost depends on
mail, accounts, add-ons, and synchronization activity. Explicit-alarm reminders
were verified functionally but were not enabled in this idle resource sample.

## Repeat the measurement

Start the widget with a complete live snapshot and let the initial read settle.
Keep the full window hidden, leave the widget visible, and avoid navigation or
editing during the sample. Record the environment, source/item counts, reminder
settings, and observation duration with the results.

Find the Dayline UI process and the Python `dayline.native_host` process. Record
their `Pss:` values from `/proc/PID/smaps_rollup` at regular intervals and average
them; do not substitute RSS, which counts shared pages in each process. Sum the
groups' mean PSS to obtain the incremental Dayline/broker figure. Separately sum
Thunderbird's main and content-process PSS, excluding the native host.

Read each group's `utime` and `stime` from `/proc/PID/stat` before and after at
least 60 seconds. Divide the summed tick difference by `getconf CLK_TCK` and by
elapsed wall seconds, then multiply by 100. Confirm the process set remains
stable; restart the sample if a process exits or a replacement starts. Report
Dayline/broker and Thunderbird independently, together with any unmet target.
