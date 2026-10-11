/* SPDX-License-Identifier: LGPL-2.0-or-later */

/* Exercise the internal out-of-bits search that caused upstream bug #490. */
#include "vbrquantize.c"
#include <stdio.h>

#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #condition); \
        return 1; \
    } \
} while (0)

int
main(void)
{
    int sfwork[SFBMAX], minima[SFBMAX], result[SFBMAX];
    int i, depth, k, peak, maximum;
    for (i = 0; i < SFBMAX; ++i) {
        /* cutDistribution can leave a band below its representable minimum. */
        sfwork[i] = i % 2 ? 160 : 200;
        minima[i] = i % 3 ? 180 : 210;
    }
    depth = sfDepth(sfwork);
    for (peak = 170; peak <= 255; ++peak) {
        for (k = 0; k <= depth; ++k) {
            maximum = flattenDistribution(sfwork, minima, result, depth, k, peak);
            CHECK(maximum >= 0 && maximum <= 255);
            for (i = 0; i < SFBMAX; ++i) {
                CHECK(result[i] >= minima[i]);
                CHECK(result[i] <= maximum);
            }
        }
    }
    for (i = 0; i < SFBMAX; ++i) {
        sfwork[i] = 255;
        minima[i] = 200;
    }
    maximum = flattenDistribution(sfwork, minima, result, sfDepth(sfwork), 0, 255);
    CHECK(maximum == 255);
    for (i = 0; i < SFBMAX; ++i)
        CHECK(result[i] == 255);
    puts("VBR scalefactor floor regression passed");
    return 0;
}
