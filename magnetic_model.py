"""Cálculo local da declinação magnética pelo World Magnetic Model 2025.

O cálculo segue a implementação Python pyGeoMag (Justin Myers, MIT), baseada
no código legado do NOAA. Os coeficientes WMM-2025 são do NOAA/NCEI.
"""
import math


_COEFICIENTES = (
    (1, 0, -29351.8, 0.0, 12.0, 0.0),
    (1, 1, -1410.8, 4545.4, 9.7, -21.5),
    (2, 0, -2556.6, 0.0, -11.6, 0.0),
    (2, 1, 2951.1, -3133.6, -5.2, -27.7),
    (2, 2, 1649.3, -815.1, -8.0, -12.1),
    (3, 0, 1361.0, 0.0, -1.3, 0.0),
    (3, 1, -2404.1, -56.6, -4.2, 4.0),
    (3, 2, 1243.8, 237.5, 0.4, -0.3),
    (3, 3, 453.6, -549.5, -15.6, -4.1),
    (4, 0, 895.0, 0.0, -1.6, 0.0),
    (4, 1, 799.5, 278.6, -2.4, -1.1),
    (4, 2, 55.7, -133.9, -6.0, 4.1),
    (4, 3, -281.1, 212.0, 5.6, 1.6),
    (4, 4, 12.1, -375.6, -7.0, -4.4),
    (5, 0, -233.2, 0.0, 0.6, 0.0),
    (5, 1, 368.9, 45.4, 1.4, -0.5),
    (5, 2, 187.2, 220.2, 0.0, 2.2),
    (5, 3, -138.7, -122.9, 0.6, 0.4),
    (5, 4, -142.0, 43.0, 2.2, 1.7),
    (5, 5, 20.9, 106.1, 0.9, 1.9),
    (6, 0, 64.4, 0.0, -0.2, 0.0),
    (6, 1, 63.8, -18.4, -0.4, 0.3),
    (6, 2, 76.9, 16.8, 0.9, -1.6),
    (6, 3, -115.7, 48.8, 1.2, -0.4),
    (6, 4, -40.9, -59.8, -0.9, 0.9),
    (6, 5, 14.9, 10.9, 0.3, 0.7),
    (6, 6, -60.7, 72.7, 0.9, 0.9),
    (7, 0, 79.5, 0.0, 0.0, 0.0),
    (7, 1, -77.0, -48.9, -0.1, 0.6),
    (7, 2, -8.8, -14.4, -0.1, 0.5),
    (7, 3, 59.3, -1.0, 0.5, -0.8),
    (7, 4, 15.8, 23.4, -0.1, 0.0),
    (7, 5, 2.5, -7.4, -0.8, -1.0),
    (7, 6, -11.1, -25.1, -0.8, 0.6),
    (7, 7, 14.2, -2.3, 0.8, -0.2),
    (8, 0, 23.2, 0.0, -0.1, 0.0),
    (8, 1, 10.8, 7.1, 0.2, -0.2),
    (8, 2, -17.5, -12.6, 0.0, 0.5),
    (8, 3, 2.0, 11.4, 0.5, -0.4),
    (8, 4, -21.7, -9.7, -0.1, 0.4),
    (8, 5, 16.9, 12.7, 0.3, -0.5),
    (8, 6, 15.0, 0.7, 0.2, -0.6),
    (8, 7, -16.8, -25.1, 0.0, 0.3),
    (8, 8, 0.9, 3.9, 0.2, 0.2),
    (9, 0, 4.6, 0.0, 0.0, 0.0),
    (9, 1, 7.8, -24.8, -0.1, -0.3),
    (9, 2, 3.0, 12.2, 0.1, 0.3),
    (9, 3, -0.2, 8.3, 0.3, -0.3),
    (9, 4, -2.5, -3.3, -0.3, 0.3),
    (9, 5, -13.1, -5.2, 0.0, 0.2),
    (9, 6, 2.4, 7.2, 0.3, -0.1),
    (9, 7, 8.6, -0.6, -0.1, -0.2),
    (9, 8, -8.7, 0.8, 0.1, 0.4),
    (9, 9, -12.9, 10.0, -0.1, 0.1),
    (10, 0, -1.3, 0.0, 0.1, 0.0),
    (10, 1, -6.4, 3.3, 0.0, 0.0),
    (10, 2, 0.2, 0.0, 0.1, 0.0),
    (10, 3, 2.0, 2.4, 0.1, -0.2),
    (10, 4, -1.0, 5.3, 0.0, 0.1),
    (10, 5, -0.6, -9.1, -0.3, -0.1),
    (10, 6, -0.9, 0.4, 0.0, 0.1),
    (10, 7, 1.5, -4.2, -0.1, 0.0),
    (10, 8, 0.9, -3.8, 0.0, -0.1),
    (10, 9, -2.7, 0.9, 0.0, 0.2),
    (10, 10, -3.9, -9.1, 0.0, 0.0),
    (11, 0, 2.9, 0.0, 0.0, 0.0),
    (11, 1, -1.5, 0.0, 0.0, 0.0),
    (11, 2, -2.5, 2.9, 0.0, 0.1),
    (11, 3, 2.4, -0.6, 0.0, 0.0),
    (11, 4, -0.6, 0.2, 0.0, 0.1),
    (11, 5, -0.1, 0.5, -0.1, 0.0),
    (11, 6, -0.6, -0.3, 0.0, 0.0),
    (11, 7, -0.1, -1.2, 0.0, 0.1),
    (11, 8, 1.1, -1.7, -0.1, 0.0),
    (11, 9, -1.0, -2.9, 0.0, 0.0),
    (11, 10, -0.2, -1.8, -0.1, 0.0),
    (11, 11, 2.6, -2.3, 0.0, 0.0),
    (12, 0, -2.0, 0.0, 0.0, 0.0),
    (12, 1, -0.2, -1.3, 0.0, 0.0),
    (12, 2, 0.3, 0.7, 0.0, 0.0),
    (12, 3, 1.2, 1.0, 0.0, -0.1),
    (12, 4, -1.3, -1.4, 0.0, 0.1),
    (12, 5, 0.6, 0.0, 0.0, 0.0),
    (12, 6, 0.6, 0.6, 0.1, 0.0),
    (12, 7, 0.5, -0.1, 0.0, 0.0),
    (12, 8, -0.1, 0.8, 0.0, 0.0),
    (12, 9, -0.4, 0.1, 0.0, 0.0),
    (12, 10, -0.2, -1.0, -0.1, 0.0),
    (12, 11, -1.3, 0.1, 0.0, 0.0),
    (12, 12, -0.7, 0.2, -0.1, -0.1),
)


def declinacao_magnetica(latitude, longitude, ano_decimal):
    """Devolve (declinação em graus, intensidade horizontal em nT).

    Leste é positivo e oeste negativo. O WMM-2025 só é válido entre 2025.0
    e 2030.0; altitude considerada: 0 km acima do elipsoide WGS 84.
    """
    if not 2025.0 <= ano_decimal <= 2030.0:
        raise ValueError("O modelo magnético WMM-2025 é válido de 2025 a 2030.")
    ordem, tamanho = 12, 13
    criar_lista = lambda n: [0.0] * n
    criar_matriz = lambda n, m: [[0.0] * m for _ in range(n)]
    c, cd = criar_matriz(tamanho, tamanho), criar_matriz(tamanho, tamanho)
    p, k = criar_lista(tamanho * tamanho), criar_matriz(tamanho, tamanho)
    fn, fm = criar_lista(tamanho), criar_lista(tamanho)

    for n, m, g, h, dg, dh in _COEFICIENTES:
        c[m][n], cd[m][n] = g, dg
        if m:
            c[n][m - 1], cd[n][m - 1] = h, dh
    p[0] = 1.0
    fm[0] = 0.0
    for n in range(1, ordem + 1):
        p[n] = p[n - 1] * float(2 * n - 1) / n
        j = 2
        for m in range(n + 1):
            k[m][n] = float((n - 1) ** 2 - m ** 2) / ((2 * n - 1) * (2 * n - 3))
            if m > 0:
                scale = float((n - m + 1) * j) / (n + m)
                p[n + m * tamanho] = p[n + (m - 1) * tamanho] * math.sqrt(scale)
                j = 1
                c[n][m - 1] *= p[n + m * tamanho]
                cd[n][m - 1] *= p[n + m * tamanho]
            c[m][n] *= p[n + m * tamanho]
            cd[m][n] *= p[n + m * tamanho]
        fn[n], fm[n] = float(n + 1), float(n)
    k[1][1] = 0.0

    lat, lon = math.radians(latitude), math.radians(longitude)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)
    s2, c2 = sin_lat * sin_lat, cos_lat * cos_lat
    a, b, re = 6378.137, 6356.7523142, 6371.2
    a2, b2 = a * a, b * b
    diff2 = a2 - b2
    q = math.sqrt(a2 - diff2 * s2)
    alt = 0.0
    q1 = alt * q
    q2 = ((q1 + a2) / (q1 + b2)) ** 2
    ct = sin_lat / math.sqrt(q2 * c2 + s2)
    st = math.sqrt(max(0.0, 1.0 - ct * ct))
    r2 = alt * alt + 2 * q1 + (a2 * a2 - diff2 * diff2 * s2) / (q * q)
    r = math.sqrt(r2)
    d = math.sqrt(a2 * c2 + b2 * s2)
    ca = (alt + d) / r
    sa = diff2 * cos_lat * sin_lat / (r * d)

    sp, cp = criar_lista(tamanho), criar_lista(tamanho)
    sp[1], cp[0], cp[1] = sin_lon, 1.0, cos_lon
    for m in range(2, ordem + 1):
        sp[m] = sp[1] * cp[m - 1] + cp[1] * sp[m - 1]
        cp[m] = cp[1] * cp[m - 1] - sp[1] * sp[m - 1]

    tc, dp, pp = criar_matriz(tamanho, tamanho), criar_matriz(tamanho, tamanho), criar_lista(tamanho)
    pp[0], dp[0][0] = 1.0, 0.0
    ar = (re / r) ** 2
    br = bt = bp = bpp = 0.0
    dt = ano_decimal - 2025.0
    for n in range(1, ordem + 1):
        ar *= re / r
        for m in range(n + 1):
            if n == m:
                p[n + m * tamanho] = st * p[n - 1 + (m - 1) * tamanho]
                dp[m][n] = st * dp[m - 1][n - 1] + ct * p[n - 1 + (m - 1) * tamanho]
            elif n == 1 and m == 0:
                p[n] = ct * p[0]
                dp[m][n] = ct * dp[m][n - 1] - st * p[0]
            elif n > 1:
                if m > n - 2:
                    p[n - 2 + m * tamanho] = 0.0
                    dp[m][n - 2] = 0.0
                p[n + m * tamanho] = ct * p[n - 1 + m * tamanho] - k[m][n] * p[n - 2 + m * tamanho]
                dp[m][n] = ct * dp[m][n - 1] - st * p[n - 1 + m * tamanho] - k[m][n] * dp[m][n - 2]
            tc[m][n] = c[m][n] + dt * cd[m][n]
            if m:
                tc[n][m - 1] = c[n][m - 1] + dt * cd[n][m - 1]
            par = ar * p[n + m * tamanho]
            if m == 0:
                temp1, temp2 = tc[m][n] * cp[m], tc[m][n] * sp[m]
            else:
                temp1 = tc[m][n] * cp[m] + tc[n][m - 1] * sp[m]
                temp2 = tc[m][n] * sp[m] - tc[n][m - 1] * cp[m]
            bt -= ar * temp1 * dp[m][n]
            bp += fm[m] * temp2 * par
            br += fn[n] * temp1 * par
            if st == 0.0 and m == 1:
                pp[n] = pp[n - 1] if n == 1 else ct * pp[n - 1] - k[m][n] * pp[n - 2]
                bpp += fm[m] * temp2 * ar * pp[n]
    bp = bpp if st == 0.0 else bp / st
    bx = -bt * ca - br * sa
    by = bp
    horizontal = math.hypot(bx, by)
    return math.degrees(math.atan2(by, bx)), horizontal

