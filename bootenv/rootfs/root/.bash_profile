# The imaging agent owns tty1. Other consoles (Alt+F2) give a normal login prompt.
if [ "$(tty)" = /dev/tty1 ]; then
  exec /usr/local/bin/mck-agent
fi
