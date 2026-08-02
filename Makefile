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
DAT_FILES := $(SOURCE_DIR)/maglev_depot.dat $(SOURCE_DIR)/maglev_station.dat $(SOURCE_DIR)/maglev_test_train.dat $(SOURCE_DIR)/maglev_track_400.dat

RUN_ARGS ?= -addons -startyear 2000 -lang en -screensize 1024x768 -nomidi

# Artwork generation. Two renderers produce the same sheet layout: a fast
# procedural 2D one, and a Blender pipeline. See tools/README.md.
PYTHON ?= python3
BLENDER ?= blender
TRACK_SHEET := $(SOURCE_DIR)/maglev_track.png
CELLS_DIR := build/cells
RENDER_SAMPLES ?= 96
REFERENCE_SHEET := upstream/infrastructure/rail_tracks/rail_400_tracks.png

.DEFAULT_GOAL := build
.PHONY: build makeobj install run status art \
        track-2d track-3d track-cells station depot vehicle head tube \
        iso-selftest preview

status:
	@printf 'Source: %s\n' '$(SOURCE_DIR)'
	@printf 'Output: %s\n' '$(OUTPUT)'
	@printf 'Makeobj: %s\n' '$(MAKEOBJ)'
	@printf 'Data files: %s\n' '$(DAT_FILES)'

makeobj:
	@test -x "$(MAKEOBJ)" || { echo "Missing makeobj: $(MAKEOBJ)"; exit 1; }

build: makeobj
	@test -n "$(DAT_FILES)" || { echo "No .dat files found in $(SOURCE_DIR)"; exit 1; }
	mkdir -p dist
	cd "$(SOURCE_DIR)" && "$(abspath $(MAKEOBJ))" PAK128 "$(abspath $(OUTPUT))" *.dat vehicles/

install: build
	mkdir -p "$(EVALUATION_USER_DIR)/addons/pak128"
	cp "$(OUTPUT)" "$(EVALUATION_USER_DIR)/addons/pak128/"

run: install
	@test -x "$(GAME_BINARY)" || { echo "Missing game binary: $(GAME_BINARY)"; exit 1; }
	"$(GAME_BINARY)" -set_basedir "$(abspath $(BASE_DIR))" -set_pakdir "$(abspath $(PAK_DIR))" -set_userdir "$(abspath $(EVALUATION_USER_DIR))" $(RUN_ARGS)

# --- artwork ---------------------------------------------------------------

# Procedural 2D sheet. Seconds to run, no Blender needed.
track-2d:
	$(PYTHON) tools/render_maglev_track.py -o "$(TRACK_SHEET)"

# Blender: render every cell, then pack them into the sheet. Falls back to
# whatever is already in the sheet for cells that failed to render.
track-cells:
	$(BLENDER) --background --python tools/blender/build_maglev_track.py -- \
		--out "$(CELLS_DIR)" --season both --samples $(RENDER_SAMPLES)

track-3d: track-cells
	$(PYTHON) tools/assemble_sheet.py "$(CELLS_DIR)" -o "$(TRACK_SHEET)" \
		--base "$(TRACK_SHEET)"

# Stop and depot. Both are buildings: two orientations, each split into a back
# image drawn before vehicles and a front image drawn after.
station depot:
	$(BLENDER) --background --python tools/blender/build_maglev_buildings.py -- \
		--object $@ --out build/$@ --samples $(RENDER_SAMPLES)
	$(PYTHON) tools/assemble_sheet.py build/$@ \
		-o "$(SOURCE_DIR)/maglev_$@.png" --sheet $@

# Rolling stock, each in its eight travel directions. The tail car reuses the
# head sheet with the directions swapped, so it has no render of its own.
vehicle:
	$(BLENDER) --background --python tools/blender/build_maglev_vehicle.py -- \
		--variant middle --out build/vehicle --samples $(RENDER_SAMPLES)
	$(PYTHON) tools/assemble_sheet.py build/vehicle \
		-o "$(SOURCE_DIR)/maglev_test_train.png" --sheet vehicle

head:
	$(BLENDER) --background --python tools/blender/build_maglev_vehicle.py -- \
		--variant head --out build/head --samples $(RENDER_SAMPLES)
	$(PYTHON) tools/assemble_sheet.py build/head \
		-o "$(SOURCE_DIR)/maglev_head.png" --sheet vehicle

# Tier 4: the enclosed glazed guideway. Two full ribi sets — back and front —
# so the sheet is four 5-row blocks, and it is written RGBA because glass
# needs real per-pixel alpha.
tube:
	$(BLENDER) --background --python tools/blender/build_maglev_track.py -- \
		--out build/tube --season both --enclosure tube --samples $(RENDER_SAMPLES)
	$(PYTHON) tools/assemble_sheet.py build/tube \
		-o "$(SOURCE_DIR)/maglev_tube.png" --sheet tube

art: track-3d station depot vehicle head tube

# Assert the Blender camera still lands on pak128's pixel grid. Run this after
# touching anything in tools/blender/simutrans_iso.py.
iso-selftest:
	$(BLENDER) --background --python tools/blender/selftest.py

# Lay the tiles out as a small map to check they join up at 100% zoom, with
# pak128's own 400km/h rail underneath for comparison.
preview:
	$(PYTHON) tools/preview_layout.py "$(TRACK_SHEET)" "$(REFERENCE_SHEET)" \
		-o build/preview.png
