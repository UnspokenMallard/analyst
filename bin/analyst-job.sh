#!/bin/zsh
# Entry point for Jarvis's scheduler (job kind "script", args = the analyst job): Jarvis keeps the clock
# and acts on the result, Odin does the work. `analyst-job.sh portfolio-advisor`, `analyst-job.sh hud-audit nightly`.
exec $HOME/.analyst/bin/analyst "$@"
