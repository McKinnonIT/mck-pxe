# The imaging agent owns tty1. Other consoles (Alt+F2) give a normal login prompt.
# MCKPXE_SHELL is set when the agent itself opens a shell ("Open a root shell"):
# don't start a second agent inside it.
if [ "$(tty)" = /dev/tty1 ] && [ -z "$MCKPXE_SHELL" ]; then
  exec /usr/local/bin/mck-agent
fi
