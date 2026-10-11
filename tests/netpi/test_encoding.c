/* SPDX-License-Identifier: LGPL-2.0-or-later */

/* Public API regression coverage for the NetPi encoding paths. */
#include <lame.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #condition); \
        exit(1); \
    } \
} while (0)

typedef struct {
    unsigned char *data;
    size_t size;
    int delay;
    int padding;
} encoded_t;

typedef struct {
    vbr_mode mode;
    int quality;
    const char *name;
} setting_t;

static float
noise_sample(uint32_t *state)
{
    *state ^= *state << 13;
    *state ^= *state >> 17;
    *state ^= *state << 5;
    return (float)((double)*state / UINT32_MAX - 0.5);
}

static void
make_pcm(float *left, float *right, int count, int rate, int silent)
{
    uint32_t noise = UINT32_C(0x1a2b3c4d);
    const double tau = 6.2831853071795864769;
    int i;
    for (i = 0; i < count; ++i) {
        const double t = (double)i / rate;
        const double envelope = (i % 1999 < 271) ? 1.0 : 0.002;
        const double fade = 1.0 - (double)i / count;
        const double sweep = tau * (57.0 * t + 0.15 * rate * t * t);
        const float l = (float)(fade * (0.21 * sin(sweep) +
                                        0.09 * sin(tau * rate * 0.43 * t)) +
                                envelope * 0.65 * noise_sample(&noise));
        const float r = (float)(fade * (0.19 * sin(1.13 * sweep) -
                                        0.09 * sin(tau * rate * 0.43 * t)) +
                                envelope * 0.65 * noise_sample(&noise));
        left[i] = silent ? 0.f : l;
        right[i] = silent ? 0.f : r;
    }
}

static encoded_t
encode(const float *left, const float *right, int count, int rate,
       int channels, const setting_t *setting, int chunked)
{
    static const int chunks[] = {1, 17, 575, 1152, 4093, 576, 127};
    const size_t capacity = (size_t)count * 2 + 32768;
    encoded_t result;
    lame_t encoder = lame_init();
    int offset, iteration, written;
    CHECK(encoder != NULL);
    result.data = malloc(capacity);
    result.size = 0;
    CHECK(result.data != NULL);
    CHECK(lame_set_num_samples(encoder, (unsigned long)count) == 0);
    CHECK(lame_set_num_channels(encoder, channels) == 0);
    CHECK(lame_set_in_samplerate(encoder, rate) == 0);
    CHECK(lame_set_out_samplerate(encoder, rate) == 0);
    CHECK(lame_set_mode(encoder, channels == 2 ? JOINT_STEREO : MONO) == 0);
    CHECK(lame_set_bWriteVbrTag(encoder, 0) == 0);
    lame_set_write_id3tag_automatic(encoder, 0);
    CHECK(lame_set_findReplayGain(encoder, 0) == 0);
    CHECK(lame_set_VBR(encoder, setting->mode) == 0);
    if (setting->mode == vbr_default)
        CHECK(lame_set_VBR_quality(encoder, 0.f) == 0);
    else if (setting->mode == vbr_abr)
        CHECK(lame_set_VBR_mean_bitrate_kbps(encoder, rate < 32000 ? 48 : 128) == 0);
    else
        CHECK(lame_set_brate(encoder, rate < 32000 ? 32 : 128) == 0);
    if (setting->quality >= 0)
        CHECK(lame_set_quality(encoder, setting->quality) == 0);
    CHECK(lame_init_params(encoder) == 0);
    for (offset = 0, iteration = 0; offset < count; ++iteration) {
        int samples = chunked ? chunks[iteration % (sizeof(chunks) / sizeof(chunks[0]))] : count;
        if (samples > count - offset)
            samples = count - offset;
        written = lame_encode_buffer_ieee_float(encoder, left + offset, right + offset,
                                                samples, result.data + result.size,
                                                (int)(capacity - result.size));
        CHECK(written >= 0);
        result.size += (size_t)written;
        CHECK(result.size < capacity);
        offset += samples;
    }
    written = lame_encode_flush(encoder, result.data + result.size,
                                (int)(capacity - result.size));
    CHECK(written >= 0);
    result.size += (size_t)written;
    CHECK(result.size > 0 && result.size <= capacity);
    result.delay = lame_get_encoder_delay(encoder);
    result.padding = lame_get_encoder_padding(encoder);
    CHECK(result.delay >= 0 && result.padding >= 0);
    CHECK(lame_close(encoder) == 0);
    return result;
}

/* Parse every frame independently of the encoder and check the declared duration. */
static void
check_frames(const encoded_t *encoded, int count, int rate, int channels)
{
    static const int rates[3] = {44100, 48000, 32000};
    static const int bitrates[2][16] = {
        {0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0},
        {0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0}
    };
    size_t offset = 0;
    int samples = 0;
    while (offset < encoded->size) {
        const unsigned char *p = encoded->data + offset;
        int version, rate_index, frame_rate, bitrate, frame_size, frame_samples;
        CHECK(encoded->size - offset >= 4);
        CHECK(p[0] == 0xff && (p[1] & 0xe0) == 0xe0);
        CHECK((p[1] & 6) == 2); /* Layer III */
        version = (p[1] >> 3) & 3;
        rate_index = (p[2] >> 2) & 3;
        CHECK(version != 1 && rate_index != 3);
        frame_rate = rates[rate_index] / (version == 3 ? 1 : version == 2 ? 2 : 4);
        CHECK(frame_rate == rate);
        CHECK(((p[3] >> 6) == 3 ? 1 : 2) == channels);
        bitrate = bitrates[version == 3][p[2] >> 4];
        CHECK(bitrate > 0);
        frame_size = (version == 3 ? 144000 : 72000) * bitrate / frame_rate;
        frame_size += (p[2] >> 1) & 1;
        frame_samples = version == 3 ? 1152 : 576;
        CHECK(frame_size > 4 && (size_t)frame_size <= encoded->size - offset);
        offset += (size_t)frame_size;
        samples += frame_samples;
    }
    CHECK(offset == encoded->size);
    CHECK(samples - encoded->delay - encoded->padding == count);
}

static void
save_encoded(const char *directory, const encoded_t *encoded, int rate,
             int channels, const setting_t *setting, int silent)
{
    char path[4096];
    FILE *output;
    int length;
    if (directory == NULL)
        return;
    length = snprintf(path, sizeof(path), "%s/%s-%d-%d-%s.mp3", directory,
                       setting->name, rate, channels, silent ? "silence" : "transients");
    CHECK(length > 0 && (size_t)length < sizeof(path));
    output = fopen(path, "wb");
    CHECK(output != NULL);
    CHECK(fwrite(encoded->data, 1, encoded->size, output) == encoded->size);
    CHECK(fclose(output) == 0);
}

static void
check_vbr_tag(int rate, int channels)
{
    const float pcm[4096] = {0};
    unsigned char output[32768], tag[4096];
    lame_t encoder = lame_init();
    int written, total, version, rate_index, tag_rate, side_info;
    size_t tag_size;
    static const int rates[] = {44100, 48000, 32000};
    CHECK(encoder != NULL);
    CHECK(lame_set_num_channels(encoder, channels) == 0);
    CHECK(lame_set_in_samplerate(encoder, rate) == 0);
    CHECK(lame_set_out_samplerate(encoder, rate) == 0);
    CHECK(lame_set_mode(encoder, channels == 2 ? JOINT_STEREO : MONO) == 0);
    CHECK(lame_set_VBR(encoder, vbr_default) == 0);
    CHECK(lame_set_VBR_quality(encoder, 0.f) == 0);
    CHECK(lame_set_bWriteVbrTag(encoder, 1) == 0);
    lame_set_write_id3tag_automatic(encoder, 0);
    CHECK(lame_init_params(encoder) == 0);
    total = lame_encode_buffer_ieee_float(encoder, pcm, pcm, 4096, output, sizeof(output));
    CHECK(total >= 0 && (size_t)total < sizeof(output));
    written = lame_encode_flush(encoder, output + total, (int)sizeof(output) - total);
    CHECK(written >= 0);
    total += written;
    memset(tag, 0xa5, sizeof(tag));
    tag_size = lame_get_lametag_frame(encoder, tag, sizeof(tag));
    CHECK(tag_size > 0 && tag_size <= sizeof(tag) && tag_size <= (size_t)total);
    CHECK(tag[0] == 0xff && (tag[1] & 0xe0) == 0xe0);
    CHECK((tag[1] & 7) == 3); /* Layer III, no CRC. */
    version = (tag[1] >> 3) & 3;
    rate_index = (tag[2] >> 2) & 3;
    CHECK(version != 1 && rate_index != 3);
    tag_rate = rates[rate_index] / (version == 3 ? 1 : version == 2 ? 2 : 4);
    CHECK(tag_rate == rate);
    CHECK(((tag[3] >> 6) == 3 ? 1 : 2) == channels);
    side_info = version == 3 ? (channels == 1 ? 17 : 32) : (channels == 1 ? 9 : 17);
    CHECK(tag_size > (size_t)side_info + 8);
    CHECK(memcmp(tag + 4 + side_info, "Xing", 4) == 0);
    CHECK(lame_close(encoder) == 0);
}

static void
check_id3_text_frames(void)
{
    lame_t encoder = lame_init();
    unsigned char tag[4096];
    size_t size, offset;
    int titles = 0, artists = 0;
    CHECK(encoder != NULL);
    id3tag_init(encoder);
    id3tag_v2_only(encoder);
    CHECK(id3tag_set_textinfo_latin1(encoder, "TIT2", "Previous title") == 0);
    CHECK(id3tag_set_textinfo_latin1(encoder, "TIT2", "Final title") == 0);
    CHECK(id3tag_set_textinfo_latin1(encoder, "TPE1", "Example artist") == 0);
    CHECK(id3tag_set_textinfo_latin1(encoder, "PRIV", "Unsupported") == -255);
    CHECK(lame_init_params(encoder) == 0);
    size = lame_get_id3v2_tag(encoder, tag, sizeof(tag));
    CHECK(size > 10 && size <= sizeof(tag));
    CHECK(memcmp(tag, "ID3", 3) == 0 && tag[3] == 3);
    for (offset = 10; offset < size && tag[offset] != 0; ) {
        const unsigned char *frame = tag + offset;
        size_t frame_size;
        CHECK(size - offset >= 10);
        frame_size = ((size_t)frame[4] << 24) | ((size_t)frame[5] << 16) |
                     ((size_t)frame[6] << 8) | frame[7];
        CHECK(frame_size > 0 && frame_size <= size - offset - 10);
        if (memcmp(frame, "TIT2", 4) == 0) {
            CHECK(frame[10] == 0 && frame_size == strlen("Final title") + 1);
            CHECK(memcmp(frame + 11, "Final title", strlen("Final title")) == 0);
            ++titles;
        }
        if (memcmp(frame, "TPE1", 4) == 0) {
            CHECK(frame[10] == 0 && frame_size == strlen("Example artist") + 1);
            CHECK(memcmp(frame + 11, "Example artist", strlen("Example artist")) == 0);
            ++artists;
        }
        offset += 10 + frame_size;
    }
    CHECK(titles == 1 && artists == 1);
    CHECK(lame_close(encoder) == 0);
}

int
main(int argc, char **argv)
{
    static const int rates[] = {8000, 22050, 32000, 44100, 48000};
    static const setting_t settings[] = {
        {vbr_default, -1, "v0"},
        {vbr_off, 0, "cbr-q0"},
        {vbr_off, 3, "cbr-q3"},
        {vbr_off, 4, "cbr-q4"},
        {vbr_abr, 0, "abr-q0"}
    };
    unsigned int rate_index, setting_index;
    int channels, silent, cases = 0;
    CHECK(argc <= 2);
    check_id3_text_frames();
    for (rate_index = 0; rate_index < sizeof(rates) / sizeof(rates[0]); ++rate_index) {
        const int rate = rates[rate_index];
        const int count = rate / 2 + 137;
        float *left = malloc((size_t)count * sizeof(*left));
        float *right = malloc((size_t)count * sizeof(*right));
        CHECK(left != NULL && right != NULL);
        for (channels = 1; channels <= 2; ++channels) {
            check_vbr_tag(rate, channels);
            for (silent = 0; silent <= 1; ++silent) {
                make_pcm(left, right, count, rate, silent);
                for (setting_index = 0; setting_index < sizeof(settings) / sizeof(settings[0]);
                     ++setting_index) {
                    const setting_t *setting = &settings[setting_index];
                    encoded_t whole = encode(left, right, count, rate, channels, setting, 0);
                    encoded_t pieces = encode(left, right, count, rate, channels, setting, 1);
                    check_frames(&whole, count, rate, channels);
                    check_frames(&pieces, count, rate, channels);
                    CHECK(whole.size == pieces.size);
                    CHECK(memcmp(whole.data, pieces.data, whole.size) == 0);
                    CHECK(whole.delay == pieces.delay && whole.padding == pieces.padding);
                    save_encoded(argc == 2 ? argv[1] : NULL, &whole, rate, channels, setting, silent);
                    free(whole.data);
                    free(pieces.data);
                    ++cases;
                }
            }
        }
        free(left);
        free(right);
    }
    printf("encoding regression: %d cases, %d encodes, 10 Xing tags and ID3 text frames passed\n",
           cases, cases * 2);
    return 0;
}
