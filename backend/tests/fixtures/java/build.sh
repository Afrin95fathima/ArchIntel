#!/usr/bin/env sh
# Rebuild the committed fixture class files. Requires a JDK (javac) on PATH or JAVA_HOME.
# Usage: backend/tests/fixtures/java/build.sh
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
OUT="$HERE/../classes"
JAVAC=${JAVA_HOME:+$JAVA_HOME/bin/}javac
PYTHON=${PYTHON:-python3}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
"$PYTHON" "$HERE/make_stubs.py" "$WORK/stubs-src" > /dev/null
mkdir -p "$WORK/stubs"
"$JAVAC" --release 17 -d "$WORK/stubs" $(find "$WORK/stubs-src" -name '*.java')
# petclinic is built like Spring Boot builds (-parameters: MethodParameters attribute); edgecases uses -g only
# (LocalVariableTable) so both ways of recovering parameter names are exercised.
for fixture in petclinic edgecases; do
  if [ "$fixture" = petclinic ]; then FLAGS='-parameters -g:source,lines'; else FLAGS='-g'; fi
  rm -rf "$OUT/$fixture"
  mkdir -p "$OUT/$fixture"
  "$JAVAC" --release 17 $FLAGS -cp "$WORK/stubs" -d "$OUT/$fixture" $(find "$HERE/$fixture" -name '*.java')
done
echo "Fixture classes written to $OUT"
