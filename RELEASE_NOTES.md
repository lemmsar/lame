LAME 4.0 maintenance fork, lemmsar revision 1.

This prerelease includes Debian 13 binaries for ARM64 and x86_64, the complete
corresponding source, SHA-256 checksums, compiler comparison reports and package
inventories. Each binary archive contains the command line encoder, shared
library, public header, license notices and a manifest identifying the source
commit, compiler and build flags.

The fork fixes VBR recovery, CBR/ABR noise shaping, resampling, allocation error
handling, Unicode CLI tags and PCM unpacking. The public library version remains
4.0 and the SONAME remains libmp3lame.so.0. Fork revisions use v4.0-r1, v4.0-r2,
and so on; an existing tag or asset must never be replaced.

The release workflow compares GCC 14, GCC 16.2, Clang 19 and Clang 23.1.3 using
native execution and generic instruction sets. Correctness checks precede the
timing comparison. Read benchmark-arm64.json and benchmark-x86_64.json for the
selected compiler and the measured workload; synthetic signals and cloud ARM
timings do not establish audible improvement or Raspberry Pi performance.

Extract an archive and run bin/lame --version. Keep bin/ and lib/ together so
the executable can locate its bundled library. These archives require Debian
13 (glibc 2.41) and the matching 64-bit CPU architecture. They do not include an
MP3 decoder; use FFmpeg to decode audio.

Verify downloads against SHA256SUMS. The NetPi integration additionally pins
each archive checksum and source commit, validates the library through FFmpeg,
and atomically activates an immutable installation. Existing source builds
remain available as an explicit fallback.

Actual Raspberry Pi playback, temperature and throughput validation is pending;
keep this release marked as a prerelease until those device checks are recorded.
