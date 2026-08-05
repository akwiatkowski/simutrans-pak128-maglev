# Build and evaluate the standalone pak128 maglev addon.

GAME_REPO ?= ../simutrans
GAME_BUILD_DIR ?= $(GAME_REPO)/build/macos
MAKEOBJ ?= $(GAME_BUILD_DIR)/src/makeobj/makeobj
GAME_BINARY ?= $(GAME_BUILD_DIR)/simutrans/simutrans.app/Contents/MacOS/simutrans

BASE_DIR ?= $(GAME_REPO)/simutrans
PAK_DIR ?= $(GAME_REPO)/pak128
EVALUATION_USER_DIR ?= evaluation/user
SOURCE_DIR := src/maglev
OUTPUT := dist/maglev-addon.pak
DAT_FILES := $(wildcard $(SOURCE_DIR)/*.dat) $(wildcard $(SOURCE_DIR)/vehicles/*.dat)

RUN_ARGS ?= -addons -startyear 2000 -lang en -screensize 1024x768 -nomidi

# Artwork generation. Two renderers produce the same sheet layout: a fast
# procedural 2D one, and a Blender pipeline. See tools/README.md.
PYTHON ?= python3
BLENDER ?= blender
# Sprite sheets live apart from the .dat files that reference them.
IMAGES_DIR := $(SOURCE_DIR)/images
# The 2D renderer keeps feeding maglev_track.png: it is the fallback base the
# per-tier 3D sheets fill failed cells from, and the quick-iteration preview.
TRACK_BASE := $(IMAGES_DIR)/maglev_track.png
TRACK_TIER_LIST := 300 500 700
CELLS_DIR := build/cells
RENDER_SAMPLES ?= 96
REFERENCE_SHEET := upstream/infrastructure/rail_tracks/rail_400_tracks.png

.DEFAULT_GOAL := build
.PHONY: build makeobj check install run status art \
        track-2d track-3d station depot concourse shelter terminal \
        fleet tube signal bridge tunnel \
        readme-trains readme-stations iso-selftest preview

status:
	@printf 'Source: %s\n' '$(SOURCE_DIR)'
	@printf 'Output: %s\n' '$(OUTPUT)'
	@printf 'Makeobj: %s\n' '$(MAKEOBJ)'
	@printf 'Data files: %s\n' '$(DAT_FILES)'

makeobj:
	@test -x "$(MAKEOBJ)" || { echo "Missing makeobj: $(MAKEOBJ)"; exit 1; }

# Validate sources before makeobj sees them. Every check here corresponds to a
# bug that has actually shipped: a renamed sheet the dat generator did not
# follow, an unconverted marker colour, and reserved colours in the icon row.
check:
	$(PYTHON) tools/check_assets.py

build: makeobj check
	@test -n "$(DAT_FILES)" || { echo "No .dat files found in $(SOURCE_DIR)"; exit 1; }
	mkdir -p dist
	cd "$(SOURCE_DIR)" && "$(abspath $(MAKEOBJ))" PAK128 "$(abspath $(OUTPUT))" *.dat vehicles/

install: build
	mkdir -p "$(EVALUATION_USER_DIR)/addons/pak128/text"
	mkdir -p "$(EVALUATION_USER_DIR)/addons/pak128/config"
	cp "$(OUTPUT)" "$(EVALUATION_USER_DIR)/addons/pak128/"
	# Simutrans loads addon display names from addons/<pak>/text/*.tab
	# (dataobj/translator.cc). Without these the depot list shows raw
	# object ids like Maglev_Meridian500_Head.
	cp "$(SOURCE_DIR)"/text/*.tab "$(EVALUATION_USER_DIR)/addons/pak128/text/"
	# Way-builder tuning for long straight guideways: the engine parses
	# addons/<pak>/config/simuconf.tab after the pakset's own (simmain.cc),
	# and the player's personal simuconf.tab still overrides it afterwards.
	cp "$(SOURCE_DIR)/config/simuconf.tab" "$(EVALUATION_USER_DIR)/addons/pak128/config/"

run: install
	@test -x "$(GAME_BINARY)" || { echo "Missing game binary: $(GAME_BINARY)"; exit 1; }
	"$(GAME_BINARY)" -set_basedir "$(abspath $(BASE_DIR))" -set_pakdir "$(abspath $(PAK_DIR))" -set_userdir "$(abspath $(EVALUATION_USER_DIR))" $(RUN_ARGS)

# --- artwork ---------------------------------------------------------------

# Per-trainset README showcases + economics paragraphs, injected between the
# trains:begin/end markers in src/maglev/README.md. Pillow only, no Blender.
readme-trains:
	$(PYTHON) tools/render_readme_trains.py

# Station gallery: each stop staged with its era's guideway and trainset,
# injected between the stations:begin/end markers.
readme-stations:
	$(PYTHON) tools/render_readme_stations.py

# Bridges: 500 viaduct, 1000 tube crossing, 4000 vacuum span.
bridge:
	for c in 500 1000 4000; do \
		$(BLENDER) --background --python tools/blender/build_maglev_bridge.py -- \
			--out "build/bridge$$c" --class $$c --samples $(RENDER_SAMPLES) && \
		$(PYTHON) tools/assemble_sheet.py "build/bridge$$c" \
			-o "$(IMAGES_DIR)/maglev_bridge$$c.png" --sheet bridge \
		|| exit 1; \
	done

# Tunnels: portal pairs per crossing class; the bore itself is invisible.
tunnel:
	for c in 500 1000 4000; do \
		$(BLENDER) --background --python tools/blender/build_maglev_tunnel.py -- \
			--out "build/tunnel$$c" --class $$c --samples $(RENDER_SAMPLES) && \
		$(PYTHON) tools/assemble_sheet.py "build/tunnel$$c" \
			-o "$(IMAGES_DIR)/maglev_tunnel$$c.png" --sheet tunnel \
		|| exit 1; \
	done

# Block + choose signals: reserved-light red/green aspects that stay lit
# after dark, packed like every other Blender sheet.
signal:
	$(BLENDER) --background --python tools/blender/build_maglev_signal.py -- \
		--out build/signal --samples $(RENDER_SAMPLES)
	$(PYTHON) tools/assemble_sheet.py build/signal \
		-o "$(IMAGES_DIR)/maglev_signal.png" --sheet signal

# Procedural 2D sheet. Seconds to run, no Blender needed.
track-2d:
	$(PYTHON) tools/render_maglev_track.py -o "$(TRACK_BASE)"

# Blender: render every cell for each open tier, then pack each into its
# sheet. Cells that failed to render fall back to the 2D base sheet.
track-3d:
	for t in $(TRACK_TIER_LIST); do \
		$(BLENDER) --background --python tools/blender/build_maglev_track.py -- \
			--out "$(CELLS_DIR)$$t" --season both --tier $$t \
			--samples $(RENDER_SAMPLES) && \
		$(PYTHON) tools/assemble_sheet.py "$(CELLS_DIR)$$t" \
			-o "$(IMAGES_DIR)/maglev_track_$$t.png" --base "$(TRACK_BASE)" \
		|| exit 1; \
	done

# Stop, depot and concourse. All are buildings: two orientations, each split
# into a back image drawn before vehicles and a front image drawn after.
station depot concourse shelter terminal:
	$(BLENDER) --background --python tools/blender/build_maglev_buildings.py -- \
		--object $@ --out build/$@ --samples $(RENDER_SAMPLES)
	$(PYTHON) tools/assemble_sheet.py build/$@ \
		-o "$(IMAGES_DIR)/maglev_$@.png" --sheet $@

# Rolling stock: every trainset in the roster, each part in its eight travel
# directions. The tail car reuses the head sheet with the directions swapped,
# so it has no render of its own.
fleet:
	$(PYTHON) tools/render_fleet.py --out "$(IMAGES_DIR)" \
		--samples $(RENDER_SAMPLES) --blender "$(BLENDER)"

# Tier 4: the enclosed glazed guideway. Two full ribi sets — back and front —
# so the sheet is four 5-row blocks, and it is written RGBA because glass
# needs real per-pixel alpha.
tube:
	for t in 1000 2000 4000; do \
		out="$(IMAGES_DIR)/maglev_tube$$t.png"; \
		[ "$$t" = "1000" ] && out="$(IMAGES_DIR)/maglev_tube.png"; \
		$(BLENDER) --background --python tools/blender/build_maglev_track.py -- \
			--out "build/tube$$t" --season both --enclosure tube --tier $$t \
			--samples $(RENDER_SAMPLES) && \
		$(PYTHON) tools/assemble_sheet.py "build/tube$$t" \
			-o "$$out" --sheet tube \
		|| exit 1; \
	done

art: track-3d station depot concourse shelter terminal fleet tube signal bridge tunnel

# Assert the Blender camera still lands on pak128's pixel grid. Run this after
# touching anything in tools/blender/simutrans_iso.py.
iso-selftest:
	$(BLENDER) --background --python tools/blender/selftest.py

# Lay the tiles out as a small map to check they join up at 100% zoom, with
# pak128's own 400km/h rail underneath for comparison.
preview:
	$(PYTHON) tools/preview_layout.py "$(IMAGES_DIR)/maglev_track_300.png" "$(REFERENCE_SHEET)" \
		-o build/preview.png
