import re
import os
import math


def ftool_to_latex(nome_arquivo):
    if not os.path.exists(nome_arquivo):
        print(f"Erro: O arquivo '{nome_arquivo}' não foi encontrado.")
        return

    with open(nome_arquivo, 'r', encoding='utf-8') as f:
        linhas = f.readlines()

    LIMITE_GEOMETRICO = 1000000
    pontos        = {}   # (x,y) -> "P1", "P2", ...
    contador_ponto = 1
    barras        = []   # lista de (P_ini, P_fim)
    nos_apoio     = {}   # nome_no -> tipo (1=pino, 2=rolete, 3=engaste)
    nos_rotula    = set()
    cargas_latex  = []

    texto = ''.join(linhas)

    # ================================================================== #
    # 1. BARRAS E PONTOS                                                   #
    # ================================================================== #
    pattern_bbox = re.compile(
        r'([+-]?\d\.\d+e[+-]\d+)\s+([+-]?\d\.\d+e[+-]\d+)\s+'
        r'([+-]?\d\.\d+e[+-]\d+)\s+([+-]?\d\.\d+e[+-]\d+)'
    )
    for x1_s, x2_s, y1_s, y2_s in pattern_bbox.findall(texto):
        xi, xf, yi, yf = float(x1_s), float(x2_s), float(y1_s), float(y2_s)
        if any(abs(v) > LIMITE_GEOMETRICO for v in [xi, xf, yi, yf]):
            continue
        p1_key = (round(xi, 4), round(yi, 4))
        p2_key = (round(xf, 4), round(yf, 4))
        for p in [p1_key, p2_key]:
            if p not in pontos:
                pontos[p] = f"P{contador_ponto}"
                contador_ponto += 1
        nova_barra = tuple(sorted((pontos[p1_key], pontos[p2_key])))
        if nova_barra not in barras and p1_key != p2_key:
            barras.append(nova_barra)

    # ================================================================== #
    # 2. BIBLIOTECA DE TIPOS DE CARGA (seção global)                     #
    #                                                                      #
    # Formato a partir da linha do nome do caso de carga:                 #
    #   'nome_caso' tipo                                                   #
    #   N_forcas_globais_diretas    (ignoradas: aplicadas fora de barras) #
    #   N_tipos_forca                                                      #
    #     'nome' Fx Fy Mz           (repete N_tipos_forca vezes)          #
    #   N_tipos_momento                                                    #
    #     'nome' pos M              (repete N_tipos_momento vezes)        #
    # ================================================================== #
    tipos_forca   = {}   # índice 1-based → (Fx, Fy, Mz)
    tipos_momento = {}   # índice 1-based → M

    lc_line = None
    for i, l in enumerate(linhas):
        if re.match(r"^\s*'\w", l) and i > 0 and linhas[i-1].strip().isdigit():
            lc_line = i
            break

    if lc_line is not None:
        cursor = lc_line + 1

        n_fg = int(linhas[cursor].strip())
        cursor += 1 + n_fg

        n_tf = int(linhas[cursor].strip())
        cursor += 1
        for k in range(1, n_tf + 1):
            partes = linhas[cursor].strip().split()
            try:
                tipos_forca[k] = (float(partes[1]), float(partes[2]), float(partes[3]))
            except (IndexError, ValueError):
                pass
            cursor += 1

        n_tm = int(linhas[cursor].strip())
        cursor += 1
        for k in range(1, n_tm + 1):
            partes = linhas[cursor].strip().split()
            try:
                tipos_momento[k] = float(partes[2])
            except (IndexError, ValueError):
                pass
            cursor += 1

    # ================================================================== #
    # 3. APOIOS, RÓTULAS E CARGAS POR BARRA                              #
    #                                                                      #
    # Bloco de barra (cabeçalho em idx):                                  #
    #   idx+0  "2 1 1 1 id_ini ... id_fim ..."  cabeçalho                #
    #   idx+1  +X_fim +Y_fim                    coord nó fim             #
    #   idx+2  0                                                          #
    #   idx+3  +X_ini +X_fim +Y_ini +Y_fim      bbox → coord nó ini      #
    #   idx+4  id h_ini h_fim 0 0 K             Tipo B (K = n_casos)     #
    #   idx+5..  bloco de K×6 linhas (flags de output, não cargas)        #
    #                                                                      #
    # Bloco pós-Tipo A (para cada nó, logo após o seu registro Tipo A):  #
    #   +1: Fx_dir Fy_dir Mz_dir   forças diretas (não via biblioteca)   #
    #   +2: n_cargas_bib            n° de cargas da biblioteca            #
    #   +3 a +2+n: para cada carga:                                       #
    #       caso(0-based) tipo_idx(0-based) ? ?                           #
    #   +3+n: flag extra                                                   #
    #                                                                      #
    # tipo_idx(0-based) + 1 = índice em tipos_forca                      #
    # ================================================================== #

    def tipo_apoio(rx, ry, rz):
        if rx == 1 and ry == 1 and rz == 0: return 1
        if rx == 0 and ry == 1 and rz == 0: return 2
        if rx == 1 and ry == 1 and rz == 1: return 3
        return None

    def eh_tipo_a(linha_str):
        p = linha_str.strip().split()
        if (len(p) == 5 and p[0].isdigit()
                and all(c in '01' for c in p[1:4])
                and re.match(r'[+-]\d\.\d+e', p[4])):
            return int(p[0]), int(p[1]), int(p[2]), int(p[3])
        return None

    def coord_ini_bbox(linha_str):
        m = re.match(
            r'\s*([+-]?\d[\d.e+\-]+)\s+[+-]?\d[\d.e+\-]+\s+([+-]?\d[\d.e+\-]+)',
            linha_str)
        if m:
            try: return float(m.group(1)), float(m.group(2))
            except ValueError: pass
        return None, None

    def angulo_forca(fx, fy):
        """
        Ângulo para a biblioteca structuralanalysis.
        A biblioteca usa Y invertido em relação à convenção matemática:
          Fy < 0 (para baixo) → 90°
          Fy > 0 (para cima)  → 270°
          Fx > 0 (para direita) → 0°
          Fx < 0 (para esquerda) → 180°
        """
        if fx == 0 and fy == 0:
            return None
        return math.degrees(math.atan2(-fy, fx)) % 360

    def processar_cargas_do_no(idx_tipo_a, nome_no):
        """
        Lê os dados de carga de um nó a partir da linha seguinte ao seu Tipo A.
        Estrutura:
          linha+1: Fx_dir Fy_dir Mz_dir   (forças diretas)
          linha+2: n_cargas_bib
          linha+3..+2+n: caso(0b) tipo_idx(0b) ? ?   (uma por linha)
          linha+3+n: flag extra
        """
        try:
            # Forças diretas (linha+1)
            partes_dir = linhas[idx_tipo_a + 1].strip().split()
            fx_dir = float(partes_dir[0])
            fy_dir = float(partes_dir[1])
            mz_dir = float(partes_dir[2]) if len(partes_dir) > 2 else 0.0

            # Cargas via biblioteca (linha+2)
            n_bib = int(linhas[idx_tipo_a + 2].strip())

            # Processar forças diretas
            if fx_dir != 0 or fy_dir != 0:
                ang = angulo_forca(fx_dir, fy_dir)
                cargas_latex.append(f"    \\load{{1}}{{{nome_no}}}[{ang:.4g}];")
            if mz_dir != 0:
                tipo_m = 2 if mz_dir < 0 else 3
                cargas_latex.append(f"    \\load{{{tipo_m}}}{{{nome_no}}};")

            # Processar cargas via biblioteca
            for k in range(n_bib):
                partes_bib = linhas[idx_tipo_a + 3 + k].strip().split()
                # tipo_idx é base-0 → +1 para índice 1-based
                tipo_idx = int(partes_bib[1]) + 1
                if tipo_idx in tipos_forca:
                    fx, fy, mz = tipos_forca[tipo_idx]
                    if fx != 0 or fy != 0:
                        ang = angulo_forca(fx, fy)
                        cargas_latex.append(f"    \\load{{1}}{{{nome_no}}}[{ang:.4g}];")
                    if mz != 0:
                        tipo_m = 2 if mz < 0 else 3
                        cargas_latex.append(f"    \\load{{{tipo_m}}}{{{nome_no}}};")
                elif tipo_idx in tipos_momento:
                    m_val = tipos_momento[tipo_idx]
                    if m_val != 0:
                        tipo_m = 2 if m_val < 0 else 3
                        cargas_latex.append(f"    \\load{{{tipo_m}}}{{{nome_no}}};")
        except (IndexError, ValueError):
            pass

    # Localizar cabeçalhos de barra
    idx_barras = [i for i, l in enumerate(linhas)
                  if re.match(r'^2\s+1\s+1\s+1\s+', l.strip())]
    apoios_registrados = set()

    for idx in idx_barras:
        partes = linhas[idx].strip().split()
        id_ini = int(partes[4])
        id_fim = int(partes[7])

        # Coord nó fim (idx+1)
        coord_fim = None
        m_fim = re.match(
            r'\s*([+-]?\d\.\d+e[+-]\d+)\s+([+-]?\d\.\d+e[+-]\d+)', linhas[idx+1])
        if m_fim:
            xf, yf = float(m_fim.group(1)), float(m_fim.group(2))
            if abs(xf) <= LIMITE_GEOMETRICO and abs(yf) <= LIMITE_GEOMETRICO:
                coord_fim = (round(xf, 4), round(yf, 4))

        # Coord nó ini via bbox (idx+3)
        coord_ini = None
        xi, yi = coord_ini_bbox(linhas[idx+3])
        if xi is not None and abs(xi) <= LIMITE_GEOMETRICO:
            coord_ini = (round(xi, 4), round(yi, 4))

        # Tipo B (idx+4): articulações + n_casos
        p_b = linhas[idx+4].strip().split()
        if len(p_b) == 6 and p_b[0].isdigit():
            hinge_ini, hinge_fim = int(p_b[1]), int(p_b[2])
            if hinge_fim == 1 and coord_fim and coord_fim in pontos:
                nos_rotula.add(pontos[coord_fim])
            if hinge_ini == 1 and coord_ini and coord_ini in pontos:
                nos_rotula.add(pontos[coord_ini])

        # Tipo A do nó ini: linha imediatamente antes do cabeçalho
        # Processa apoio E cargas do nó ini
        if coord_ini and coord_ini in pontos:
            nome_ini = pontos[coord_ini]
            for back in range(idx - 1, max(idx - 10, -1), -1):
                result = eh_tipo_a(linhas[back])
                if result is not None:
                    id_no, rx, ry, rz = result
                    if id_no == id_ini:
                        # Apoio
                        if nome_ini not in apoios_registrados:
                            tipo = tipo_apoio(rx, ry, rz)
                            if tipo:
                                nos_apoio[nome_ini] = tipo
                            apoios_registrados.add(nome_ini)
                        # Cargas do nó ini
                        processar_cargas_do_no(back, nome_ini)
                    break

    # Tipo A do nó fim da última barra: apoio + cargas
    if idx_barras:
        ultimo = idx_barras[-1]
        partes_ult = linhas[ultimo].strip().split()
        id_fim_ult = int(partes_ult[7])
        m = re.match(
            r'\s*([+-]?\d\.\d+e[+-]\d+)\s+([+-]?\d\.\d+e[+-]\d+)', linhas[ultimo+1])
        if m:
            xf_ult, yf_ult = float(m.group(1)), float(m.group(2))
            coord_fim_ult = (round(xf_ult, 4), round(yf_ult, 4))
            if coord_fim_ult in pontos:
                nome_fim_ult = pontos[coord_fim_ult]
                for fwd in range(ultimo + 5, min(ultimo + 20, len(linhas))):
                    result = eh_tipo_a(linhas[fwd])
                    if result is not None:
                        id_no, rx, ry, rz = result
                        if id_no == id_fim_ult:
                            # Apoio
                            if nome_fim_ult not in apoios_registrados:
                                tipo = tipo_apoio(rx, ry, rz)
                                if tipo:
                                    nos_apoio[nome_fim_ult] = tipo
                                apoios_registrados.add(nome_fim_ult)
                            # Cargas do nó fim
                            processar_cargas_do_no(fwd, nome_fim_ult)
                        break

    # Remover duplicatas mantendo ordem
    vistos = set()
    cargas_unicas = [c for c in cargas_latex
                     if not (c in vistos or vistos.add(c))]

    # ================================================================== #
    # 4. GERAÇÃO DO CÓDIGO LATEX                                          #
    # ================================================================== #
    print("\n% --- CÓDIGO LATEX ---")
    print(r"\begin{tikzpicture}")
    print(r"    \scaling{1.2};")

    sorted_points = sorted(pontos.items(), key=lambda x: int(x[1][1:]))

    print("\n    % Pontos")
    for (x, y), name in sorted_points:
        print(f"    \\point{{{name}}}{{{x:g}}}{{{y:g}}};")

    if nos_apoio:
        print("\n    % Apoios")
        for name, tipo in sorted(nos_apoio.items(), key=lambda x: int(x[0][1:])):
            print(f"    \\support{{{tipo}}}{{{name}}};")

    if nos_rotula:
        print("\n    % Rótulas")
        for name in sorted(nos_rotula, key=lambda x: int(x[1:])):
            print(f"    \\hinge{{1}}{{{name}}};")

    print("\n    % Elementos de Barra")
    for p_ini, p_fim in barras:
        print(f"    \\beam{{2}}{{{p_ini}}}{{{p_fim}}};")

    if cargas_unicas:
        print("\n    % Carregamentos")
        for cmd in cargas_unicas:
            print(cmd)

    print(r"\end{tikzpicture}")
    print("% --- FIM DO CÓDIGO ---")


# --- EXECUÇÃO ---
ftool_to_latex('2_822.ftl')
