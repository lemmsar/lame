/* SPDX-License-Identifier: LGPL-2.0-or-later */

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "config.h"
#include "lame.h"
#include "machine.h"
#include "encoder.h"
#include "util.h"
#include "lame_global_flags.h"

#define CHECK(c) do { if (!(c)) { fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #c); abort(); } } while (0)

static void duration(int rate, int channels)
{
    lame_t g = lame_init();
    short pcm[1152];
    unsigned char mp3[16384];
    int left = rate * 2, offset = 0, i, n;
    long samples;
    CHECK(g != NULL);
    CHECK(lame_set_num_channels(g, channels) == 0);
    CHECK(lame_set_in_samplerate(g, rate) == 0);
    CHECK(lame_set_out_samplerate(g, 44100) == 0);
    CHECK(lame_set_VBR(g, vbr_default) == 0);
    CHECK(lame_set_VBR_quality(g, 0) == 0);
    CHECK(lame_init_params(g) == 0);
    CHECK(isResamplingNecessary(&g->internal_flags->cfg) == (rate != 44100));
    while (left > 0) {
        n = left < 1152 ? left : 1152;
        for (i = 0; i < n; ++i)
            pcm[i] = (short)(12000 * sin(6.283185307179586 * 997 * (offset + i) / rate));
        CHECK(lame_encode_buffer(g, pcm, pcm, n, mp3, sizeof(mp3)) >= 0);
        offset += n;
        left -= n;
    }
    CHECK(lame_encode_flush(g, mp3, sizeof(mp3)) >= 0);
    samples = (long)lame_get_frameNum(g) * lame_get_framesize(g)
        - lame_get_encoder_delay(g) - lame_get_encoder_padding(g);
    /* The FIR/flush boundary can round by one sample. */
    CHECK(labs(samples - 88200) <= 1);
    CHECK(lame_close(g) == 0);
}
static void noise_shaping(void)
{
    vbr_mode modes[] = {vbr_off, vbr_abr, vbr_mtrh};
    int m, q;
    for (m = 0; m < 3; ++m) {
        for (q = 0; q <= 9; ++q) {
            lame_t g = lame_init();
            CHECK(g != NULL);
            CHECK(lame_set_VBR(g, modes[m]) == 0);
            CHECK(lame_set_quality(g, q) == 0);
            CHECK(lame_init_params(g) == 0);
            if (modes[m] == vbr_off || modes[m] == vbr_abr)
                CHECK(g->internal_flags->cfg.noise_shaping_amp == 0);
            else if (q <= 3)
                CHECK(g->internal_flags->cfg.noise_shaping_amp > 0);
            CHECK(lame_close(g) == 0);
        }
    }
}
int main(void)
{
    int rates[] = {44090, 44099, 44100, 44101, 44110, 32000, 48000, 96000};
    int i, channels;
    for (channels = 1; channels <= 2; ++channels)
        for (i = 0; i < (int)(sizeof(rates) / sizeof(rates[0])); ++i)
            duration(rates[i], channels);
    noise_shaping();
    puts("resampling duration and CBR/ABR quality configuration passed");
    return 0;
}
