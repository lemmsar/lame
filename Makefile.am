## $Id$
# Modified for the lemmsar/lame maintenance fork on 2026-10-11.

include $(top_srcdir)/Makefile.am.global

ACLOCAL_AMFLAGS=-I m4

.PHONY: test check-netpi

SUBDIRS = mpglib libmp3lame frontend Dll doc include misc dshow ACM \
	mac vc_solution

CLEANFILES = testcase.new.mp3

EXTRA_DIST = \
	.github/workflows/ci.yml \
	.github/workflows/release.yml \
	API \
	CONTRIBUTING.md \
	DEFINES \
	HACKING \
	INSTALL.configure \
	LICENSE \
	Makefile.MSVC \
	Makefile.unix \
	Makefile.am.global \
	README.WINGTK \
	README.md \
	README.netpi \
	RELEASE_VERSION \
	RELEASE_NOTES.md \
	RELEASING.md \
	STYLEGUIDE \
	USAGE \
	configMS.h \
	debian \
	doc/COMPILER_BENCHMARKS.md \
	doc/upstream/README \
	doc/upstream/HACKING \
	doc/upstream/LICENSE \
	lame.bat \
	lame.spec.in \
	lame.spec \
	scripts/build-netpi.py \
	scripts/build-release.sh \
	scripts/prepare-release-toolchains.sh \
	scripts/benchmark-compilers.py \
	scripts/package-release.py \
	scripts/assemble-release.py \
	scripts/export-netpi-patch.py \
	tests/netpi/run-tests.sh \
	tests/netpi/run-encoding-tests.sh \
	tests/netpi/test_allocations.c \
	tests/netpi/test_build_profiles.py \
	tests/netpi/test_encoding.c \
	tests/netpi/test_frontend.py \
	tests/netpi/test_installer.py \
	tests/netpi/test_release_package.py \
	tests/netpi/test_neon.c \
	tests/netpi/test_resampler.c \
	tests/netpi/test_vbr_quantize.c \
	testcase.mp3 \
	testcase.wav

# Requires a static library and GNU-compatible linker wrapping; see CONTRIBUTING.md.
check-netpi: all
	CC="$(CC)" CFLAGS="$(CFLAGS)" LDFLAGS="$(LDFLAGS)" \
	  bash "$(top_srcdir)/tests/netpi/run-tests.sh" "$(abs_top_builddir)"

#
# The differences depend on the used processor architecture, the used
# compiler and the used options for the compiler, so make test may
# show some differences. You should only be concerned if you are a
# LAME developer and the number of differences change after you
# modified the source.
#
testcase.new.mp3: testcase.wav frontend/lame$(EXEEXT)
	time frontend/lame$(EXEEXT) --nores $(top_srcdir)/testcase.wav testcase.new.mp3 || $(RM_F) testcase.new.mp3

test: testcase.mp3 testcase.new.mp3
	@echo
	@echo "The following output has value only for a LAME-developer, do not make _any_"
	@echo "assumptions about what this number means. You do not need to care about it."
	@cmp -l testcase.new.mp3 $(top_srcdir)/testcase.mp3 | wc -l

testupdate: testcase.new.mp3
	cp testcase.new.mp3 $(top_srcdir)/testcase.mp3

testg: frontend/mp3x$(EXEEXT) $(top_srcdir)/../test/castanets.wav
	frontend/mp3x$(EXEEXT) -h $(top_srcdir)/../test/castanets.wav

update:
	cd $(top_srcdir) && svn update || true

diff:
	cd $(top_srcdir) && svn diff || true

frontend/lame$(EXEEXT):
	$(MAKE) $(MAKEFLAGS)

frontend/mp3x$(EXEEXT): frontend/lame$(EXEEXT)

