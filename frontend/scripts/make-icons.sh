#!/usr/bin/env bash
#
# Build every app icon from one square logo render.
#
#   ./scripts/make-icons.sh scripts/logo-source.jpg
#
# The source is expected to be a dark mark on a plain light background —
# what an image model hands back. Everything downstream is derived, so
# regenerating after a logo tweak is one command.
#
# Outputs land where the Next.js App Router looks for them (app/icon.png,
# app/apple-icon.png, app/opengraph-image.png); Next emits the <link> tags
# itself, so nothing needs wiring by hand.
#
# Requires ImageMagick 7 (`brew install imagemagick`).

set -euo pipefail

SRC="${1:-}"
[ -n "$SRC" ] && [ -f "$SRC" ] || { echo "usage: $0 <logo.(jpg|png)>" >&2; exit 1; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$HERE/../app"
PUB="$HERE/../public"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Monochrome identity: a white mark on black. The letterforms carry the
# brand, so colour is left to the interface rather than the logo.
BG="#000000"       # icon and preview-card background
PANEL="#000000"    # badge fill
BORDER="#2a2a2a"   # just enough edge to separate the badge from a dark tab
MARK="white"
INK="#ffffff"
MUTED="#9aa3b2"
MONO="/System/Library/Fonts/Menlo.ttc"

mkdir -p "$APP" "$PUB"

echo "→ isolating the mark"
# Trim the flat border, then drop the light background to alpha. The fuzz is
# generous because a JPEG's "white" is never exactly #ffffff — it carries
# compression noise around every edge.
magick "$SRC" \
  -fuzz 12% -trim +repage \
  -fuzz 30% -transparent white \
  "$WORK/mark.png"

# Two substitutions rather than `read W H`: `identify -format` emits no
# trailing newline, so `read` returns non-zero at EOF and `set -e` would
# kill the script on a step that actually succeeded.
W=$(magick identify -format "%w" "$WORK/mark.png")
H=$(magick identify -format "%h" "$WORK/mark.png")
echo "  mark is ${W}x${H}"

# Recolour by masking a solid fill with the mark's own alpha. Colorize would
# muddy the anti-aliased edges; this keeps them clean.
recolour() { # $1=colour $2=out
  magick -size "${W}x${H}" "xc:$1" \
    \( "$WORK/mark.png" -alpha extract \) \
    -alpha off -compose CopyOpacity -composite "$2"
}
recolour "$MARK" "$WORK/mark-white.png"

# A rounded-square badge so the icon reads as one shape on any tab colour.
badge() { # $1=size $2=out
  local s=$1 r=$(( $1 * 22 / 100 )) inset
  inset=$(( s - 1 ))
  magick -size "${s}x${s}" xc:none \
    -fill "$PANEL" -stroke "$BORDER" -strokewidth "$(( s / 64 + 1 ))" \
    -draw "roundrectangle 0,0 ${inset},${inset} ${r},${r}" "$2"
}

compose_badge() { # $1=size $2=mark $3=out
  # 80% rather than a polite two-thirds: at 32px and below the mark is the
  # only thing anyone can resolve, so the badge earns as little padding as
  # still reads as a badge.
  local s=$1 inner=$(( $1 * 80 / 100 ))
  badge "$s" "$WORK/badge-$s.png"
  magick "$WORK/badge-$s.png" \
    \( "$2" -resize "${inner}x${inner}" \) \
    -gravity center -compose over -composite "$3"
}

echo "→ app/icon.png (browser tab)"
compose_badge 512 "$WORK/mark-white.png" "$APP/icon.png"

echo "→ app/apple-icon.png (iOS home screen)"
# iOS masks the corners itself and never shows transparency, so this one is
# a filled square rather than a rounded badge.
magick -size 180x180 "xc:$PANEL" \
  \( "$WORK/mark-white.png" -resize 124x124 \) \
  -gravity center -composite "$APP/apple-icon.png"

echo "→ public/logo-mark.png (nav, transparent)"
magick "$WORK/mark-white.png" -resize 256x256 "$PUB/logo-mark.png"

echo "→ app/opengraph-image.png (link previews)"
# `-gravity` is sticky in ImageMagick: the value set for the composite is
# still in force when -annotate runs, which throws every coordinate off. Set
# it back to northwest explicitly so the text offsets are plain top-left.
magick -size 1200x630 "xc:$BG" \
  \( "$WORK/mark-white.png" -resize 320x320 \) -gravity west -geometry +100+0 -composite \
  -gravity northwest -font "$MONO" \
  `# y is the TOP of each text box under northwest gravity, not the` \
  `# baseline — lines need their full point size cleared beneath them.` \
  -fill "$INK"    -pointsize 76 -annotate +470+228 "quant.futures" \
  -fill "$MUTED"  -pointsize 28 -annotate +474+352 "CME index futures analytics" \
  -fill "$MUTED"  -pointsize 24 -annotate +474+400 "quant.samlabhq.com" \
  "$APP/opengraph-image.png"

echo "→ app/favicon.ico (multi-resolution)"
# 16px cannot hold the badge AND the letterforms, so that entry drops the
# badge and lets the mark fill the frame. Browsers pick the size they need
# out of the .ico, so the small case gets its own artwork rather than a
# blurred-down copy of the large one.
magick "$WORK/mark-white.png" -resize 16x16 -background none -gravity center -extent 16x16 "$WORK/ico-16.png"
magick "$APP/icon.png" -resize 32x32 "$WORK/ico-32.png"
magick "$APP/icon.png" -resize 48x48 "$WORK/ico-48.png"
magick "$WORK/ico-16.png" "$WORK/ico-32.png" "$WORK/ico-48.png" "$APP/favicon.ico"

echo "→ favicon legibility check"
# Renders each .ico entry at 4x so the small sizes can actually be judged.
magick -size 420x150 "xc:$PANEL" \
  \( "$WORK/ico-16.png" -scale 400% \) -gravity west -geometry +30+0 -composite \
  \( "$WORK/ico-32.png" -scale 400% \) -gravity west -geometry +120+0 -composite \
  \( "$WORK/ico-48.png" -scale 200% \) -gravity west -geometry +280+0 -composite \
  "$WORK/zoom.png"
magick -size 420x60 "xc:$PANEL" \
  \( "$WORK/ico-16.png" \) -gravity west -geometry +48+0 -composite \
  \( "$WORK/ico-32.png" \) -gravity west -geometry +150+0 -composite \
  \( "$WORK/ico-48.png" \) -gravity west -geometry +300+0 -composite \
  "$WORK/actual.png"
magick "$WORK/zoom.png" "$WORK/actual.png" -append "$PUB/icon-size-check.png"

echo
echo "done:"
for f in "$APP/icon.png" "$APP/favicon.ico" "$APP/apple-icon.png" "$APP/opengraph-image.png" \
         "$PUB/logo-mark.png"; do
  printf "  %-34s %s\n" "${f#"$HERE/../"}" "$(magick identify -format '%wx%h %b' "$f")"
done
