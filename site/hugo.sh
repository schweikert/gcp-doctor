#!/bin/sh

if [ "$#" -eq 0 ]; then
    ARGS=""
elif [ "$1" = "server" ]; then
    shift
    ARGS="server --bind 0.0.0.0 -b http://localhost:1313 $@"
else
    ARGS="$@"
fi

docker run \
  --rm \
  -it \
  -u "$(id -u):$(id -g)" \
  -e "USER=$(id -n -u)" \
  -e "GROUP=$(id -n -g)" \
  -e "SHELL=/bin/bash" \
  -e HOME -e LANG \
  -v $(pwd):/src \
  -p 1313:1313 \
  docsy-test:latest \
  hugo \
  --themesDir=/themes \
  $ARGS
