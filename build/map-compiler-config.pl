# Config for the vendored xonotic-map-compiler. Installed to ~/.xonotic-map-compiler, which the
# wrapper `do`s after setting its own defaults — the supported override hook, so build/vendor/ stays
# byte-identical to upstream and refreshing it is a straight recopy.
#
# Every path comes from the environment so this file needs no editing per machine:
#   VORTEXARENA_ROOT   the VortexArena CHECKOUT ROOT - the directory that CONTAINS data/, not data/
#                      itself. q3map2 resolves `-fs_basepath X -game xonotic` as X/data/, so pointing
#                      this at .../VortexArena/data would make it look for .../VortexArena/data/data/.
#   VORTEXMAPS_Q3MAP2  the q3map2 binary
#
# Why the game's tree is needed at all when this repo holds the map sources: a few things a map
# references live in the game's core content rather than in sources/ - measured across all 31 maps,
# one of 54 referenced texture sets (`domination`, 1.4 MB) plus core's scripts/ at 124 KB. q3map2 reads
# .pk3dir as a pack (netradiant tools/quake3/common/vfs.c:240), so a basepath at the checkout root
# exposes data/core.pk3dir/ without any unpacking. See build/vendor/README.md.
#
# The wrapper supplies the OTHER basepath itself: it symlinks <tmpdir>/data -> the map's parent
# directory, which is how our type-rooted sources/ works with no overlay step.

our $XONOTICDIR = $ENV{VORTEXARENA_ROOT} || Cwd::getcwd();
our $Q3MAP2     = $ENV{VORTEXMAPS_Q3MAP2} || 'q3map2';

# Upstream forbids reading the shipped pk3s so a compile cannot silently pick up already-built content
# instead of the sources. Kept verbatim: our sources/ holds no pk3s, so it is belt-and-braces, but it is
# exactly the kind of guard worth keeping. -threads is left to q3map2's default (all cores).
our $Q3MAP2FLAGS = '-fs_forbiddenpath xonotic*-data*.pk3* '
                 . '-fs_forbiddenpath xonotic*-nexcompat*.pk3* '
                 . '-fs_forbiddenpath xonotic*-xoncompat*.pk3* '
                 . '-fs_forbiddenpath *-q3map2.zip '
                 . '-fs_forbiddenpath shared-*.zip';

# Per-phase defaults stay exactly as upstream ships them. Each map's own .map.options then adds or
# overrides on top, which is the whole point: those per-map flags are deliberate authoring decisions.
# Do NOT "normalise" them here.

1;
