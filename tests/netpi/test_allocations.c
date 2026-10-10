/* Link with the static encoder and -Wl,--wrap=calloc,--wrap=malloc,--wrap=free. */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include "config.h"
#include "lame.h"
#include "machine.h"
#include "encoder.h"
#include "util.h"
#include "lame_global_flags.h"

#define CHECK(c) do { if (!(c)) { fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #c); abort(); } } while (0)
#define MAX_ALLOCS 4096
static void *live[MAX_ALLOCS];
static int live_count, armed, call_count, fail_at;
static uint32_t baseline_hash;
void *__real_malloc(size_t);
void *__real_calloc(size_t, size_t);
void __real_free(void *);

static void *remember(void *p)
{
    int i;
    if (p == NULL)
        return p;
    for (i = 0; i < MAX_ALLOCS; ++i) {
        if (live[i] == NULL) {
            live[i] = p;
            ++live_count;
            return p;
        }
    }
    abort();
}
void *__wrap_malloc(size_t n)
{
    if (armed && ++call_count == fail_at)
        return NULL;
    return remember(__real_malloc(n));
}
void *__wrap_calloc(size_t n, size_t size)
{
    if (armed && ++call_count == fail_at)
        return NULL;
    return remember(__real_calloc(n, size));
}
void __wrap_free(void *p)
{
    int i;
    if (p != NULL) {
        for (i = 0; i < MAX_ALLOCS; ++i) {
            if (live[i] == p) {
                live[i] = NULL;
                --live_count;
                break;
            }
        }
        CHECK(i < MAX_ALLOCS);
    }
    __real_free(p);
}
static void arm(int at)
{
    call_count = 0;
    fail_at = at;
    armed = 1;
}
static uint32_t encode(lame_t g)
{
    short pcm[2048];
    unsigned char mp3[16384];
    uint32_t hash = 2166136261u;
    int i, count;
    for (i = 0; i < 2048; ++i)
        pcm[i] = (short)((i * 997) % 24000 - 12000);
    count = lame_encode_buffer(g, pcm, pcm, 2048, mp3, sizeof(mp3));
    CHECK(count >= 0);
    for (i = 0; i < count; ++i)
        hash = (hash ^ mp3[i]) * 16777619u;
    count = lame_encode_flush(g, mp3, sizeof(mp3));
    CHECK(count >= 0);
    for (i = 0; i < count; ++i)
        hash = (hash ^ mp3[i]) * 16777619u;
    return hash;
}
static lame_t configured(int rate, int rg, int tags)
{
    lame_t g = lame_init();
    CHECK(g != NULL);
    CHECK(lame_set_in_samplerate(g, rate) == 0);
    CHECK(lame_set_out_samplerate(g, 44100) == 0);
    CHECK(lame_set_VBR(g, vbr_default) == 0);
    CHECK(lame_set_VBR_quality(g, 0) == 0);
    CHECK(lame_set_findReplayGain(g, rg) == 0);
    if (tags) {
        id3tag_init(g);
        id3tag_set_title(g, "allocation failure regression");
        id3tag_add_v2(g);
    }
    return g;
}
static int initialization(int rate, int rg, int tags, int failure, int retry)
{
    lame_t g = configured(rate, rg, tags);
    int rc, count;
    CHECK(g->internal_flags->sv_rpg.rgdata == NULL);
    arm(failure);
    rc = lame_init_params(g);
    count = call_count;
    armed = 0;
    if (failure) {
        CHECK(count >= failure);
        CHECK(rc == -2);
        CHECK(g->internal_flags->lame_init_params_successful == 0);
        if (retry)
            CHECK(lame_init_params(g) == 0);
    }
    else {
        CHECK(rc == 0);
    }
    if (!failure || retry) {
        uint32_t hash;
        CHECK((g->internal_flags->sv_rpg.rgdata != NULL) == rg);
        hash = encode(g);
        if (!failure)
            baseline_hash = hash;
        else
            CHECK(hash == baseline_hash);
    }
    CHECK(lame_close(g) == 0);
    CHECK(live_count == 0);
    return count;
}
static void input_buffers(void)
{
    int failure;
    initialization(44100, 0, 0, 0, 0);
    for (failure = 1; failure <= 2; ++failure) {
        lame_t g = configured(44100, 0, 0);
        short pcm[2048] = {0};
        unsigned char mp3[16384];
        CHECK(lame_init_params(g) == 0);
        arm(failure);
        CHECK(lame_encode_buffer(g, pcm, pcm, 2048, mp3, sizeof(mp3)) == -2);
        armed = 0;
        CHECK(encode(g) == baseline_hash);
        CHECK(lame_close(g) == 0);
        CHECK(live_count == 0);
    }
}
int main(void)
{
    int modes[][3] = {{44100, 0, 0}, {44100, 1, 1}, {44099, 0, 0}, {48000, 1, 0}};
    int m, n, count, total = 0;
    lame_t g;
    arm(0);
    g = lame_init();
    count = call_count;
    armed = 0;
    CHECK(g != NULL);
    /* Closing before init_params releases the instance and reports -3. */
    CHECK(lame_close(g) == -3);
    for (n = 1; n <= count; ++n) {
        arm(n);
        g = lame_init();
        armed = 0;
        CHECK(g == NULL);
        CHECK(live_count == 0);
        ++total;
    }
    for (m = 0; m < (int)(sizeof(modes) / sizeof(modes[0])); ++m) {
        count = initialization(modes[m][0], modes[m][1], modes[m][2], 0, 0);
        for (n = 1; n <= count; ++n) {
            initialization(modes[m][0], modes[m][1], modes[m][2], n, 0);
            initialization(modes[m][0], modes[m][1], modes[m][2], n, 1);
            ++total;
        }
    }
    input_buffers();
    printf("allocation failures: %d initialization points plus input buffers passed\n", total);
    return 0;
}
