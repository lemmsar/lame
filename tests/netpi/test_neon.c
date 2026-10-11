/* SPDX-License-Identifier: LGPL-2.0-or-later */

/* Regression for the optional ARM64 integer Huffman counting routine.
 * Build together with neon_choose_table.c and tables.c, using the build's
 * config.h and the include/libmp3lame header paths. Exit 77 means unsupported.
 */
#ifdef HAVE_CONFIG_H
# include <config.h>
#endif

#include <stdio.h>
#include <stdlib.h>

#include "lame.h"
#include "machine.h"
#include "encoder.h"
#include "util.h"
#include "tables.h"
#include "vector/lame_intrin.h"

#ifdef HAVE_NEON_INTRINSICS
static unsigned int
scalar_count(const int *values, int length, unsigned int linbits)
{
    unsigned int sum = 0;
    int i;
    for (i = 0; i < length; i += 2) {
        unsigned int x = (unsigned int) values[i];
        unsigned int y = (unsigned int) values[i + 1];
        if (x >= 15) {
            x = 15;
            sum += linbits;
        }
        if (y >= 15) {
            y = 15;
            sum += linbits;
        }
        sum += largetbl[(x << 4) + y];
    }
    return sum;
}

static uint32_t
random_value(uint32_t *state)
{
    *state ^= *state << 13;
    *state ^= *state >> 17;
    *state ^= *state << 5;
    return *state;
}
#endif

int
main(void)
{
#ifdef HAVE_NEON_INTRINSICS
    static const int boundaries[] = { 0, 1, 14, 15, 16, 17, 255, 8191, 8206 };
    uint32_t state = 0x59cbce1du;
    int length, pattern, offset;
    unsigned long cases = 0;

    /* Every legal region length, including all vector tails, is checked.
     * Exact-sized allocations let ASan detect reads beyond the region.
     * Offsets also exercise each alignment of the first vector load.
     */
    for (length = 0; length <= 576; length += 2) {
        for (offset = 0; offset < 4; ++offset) {
            size_t count = (size_t) (length + offset);
            int *storage = malloc((count ? count : 1) * sizeof(*storage));
            int *values;
            if (!storage) {
                fputs("allocation failed\n", stderr);
                return 1;
            }
            values = storage + offset;
            for (pattern = 0; pattern < 24; ++pattern) {
                unsigned int vector_sum, nclamped, t1;
                int i;
                for (i = 0; i < length; ++i) {
                    if (pattern < 9)
                        values[i] = boundaries[pattern];
                    else if (pattern == 9)
                        values[i] = boundaries[i % 9];
                    else
                        values[i] = (int) (random_value(&state) % 8207u);
                }
                vector_sum = count_bit_esc_neon(values, values + length,
                                                largetbl, &nclamped);
                for (t1 = 16; t1 < 32; ++t1) {
                    {
                        unsigned int t2 = 16u + ((t1 + (unsigned int) pattern) % 16u);
                        unsigned int linbits = ht[t1].xlen * 65536u + ht[t2].xlen;
                        unsigned int actual = vector_sum + nclamped * linbits;
                        unsigned int expected = scalar_count(values, length, linbits);
                        if (actual != expected) {
                            fprintf(stderr,
                                    "NEON mismatch: length=%d offset=%d pattern=%d "
                                    "tables=%u/%u expected=%u actual=%u\n",
                                    length, offset, pattern, t1, t2, expected, actual);
                            free(storage);
                            return 1;
                        }
                        ++cases;
                    }
                }
            }
            free(storage);
        }
    }
    printf("NEON matches scalar Huffman counts in %lu cases\n", cases);
    return 0;
#else
    puts("SKIP: this build does not enable ARM64 NEON");
    return 77;
#endif
}
