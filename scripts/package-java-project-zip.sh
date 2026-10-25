#!/usr/bin/env bash
# Bundle a built multi-module Java project for ArchIntel: every target/classes or build/classes .class file, plus the
# build descriptors (pom.xml, Gradle files) ArchIntel uses to resolve dependency versions. macOS/Linux twin of
# package-java-project-zip.ps1.
#   scripts/package-java-project-zip.sh <source-root> <output.zip> [max-upload-mb]
set -euo pipefail
source_root="${1:?usage: package-java-project-zip.sh <source-root> <output.zip> [max-upload-mb]}"
output="${2:?usage: package-java-project-zip.sh <source-root> <output.zip> [max-upload-mb]}"
max_mb="${3:-100}"
root="$(cd "$source_root" && pwd)"
mkdir -p "$(dirname "$output")"
output="$(cd "$(dirname "$output")" && pwd)/$(basename "$output")"
case "$output" in "$root"/*) echo 'Choose an output ZIP path outside the source checkout.' >&2; exit 1;; esac
[ -e "$output" ] && { echo 'Output ZIP already exists. Choose a new output path so an existing file is preserved.' >&2; exit 1; }
skip='/(\.git|node_modules|\.m2|deps|dependencies|\.gradle)/'
list="$(mktemp)"; trap 'rm -f "$list"' EXIT
(cd "$root" && find . -type f -name '*.class' | grep -E '/(target|build)/classes/' | grep -Ev "$skip" | sed 's|^\./||') > "$list"
classes=$(wc -l < "$list" | tr -d ' ')
[ "$classes" -gt 0 ] || { echo 'No compiled Java classes found. Build the application first, then run this script again.' >&2; exit 1; }
(cd "$root" && find . -type f \( -name pom.xml -o -name build.gradle -o -name build.gradle.kts -o -name settings.gradle -o -name settings.gradle.kts \) \
  | grep -Ev '/(target|build|\.git|node_modules|\.m2|\.gradle)/' | sed 's|^\./||') >> "$list"
descriptors=$(( $(wc -l < "$list" | tr -d ' ') - classes ))
(cd "$root" && zip -q -X "$output" -@ < "$list")
size=$(wc -c < "$output" | tr -d ' ')
if [ "$size" -gt $(( max_mb * 1024 * 1024 )) ]; then
  rm -f "$output"
  echo "ZIP is $(( size / 1048576 )) MiB, above ArchIntel's ${max_mb} MiB upload limit. Package fewer modules or raise the configured upload limit." >&2
  exit 1
fi
echo "Created compiled Java project bundle: $output"
echo "Included $classes class files and $descriptors build descriptors; compressed size $(( size / 1048576 )) MiB."
