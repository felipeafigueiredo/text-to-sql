"""Recorte do Yelp Open Dataset: uma cidade inteira, pronta para o PostgreSQL e o Neo4j.

Lê os JSON originais linha a linha (sem carregar tudo na memória) e grava CSV pequenos:

    business.csv            -> PostgreSQL (tabela business) e Neo4j (nós Business)
    business_category.csv   -> PostgreSQL
    users.csv               -> PostgreSQL (tabela users) e Neo4j (nós User)
    review.csv              -> PostgreSQL (sem o texto da review)
    friends.csv             -> Neo4j (uma linha por amizade, sem repetição)
    reviewed.csv            -> Neo4j (uma linha por par usuário-negócio)

Uso:
    python dados/recorte.py <pasta_dos_json> <pasta_de_saida> [--cidade "Santa Barbara"] [--estado CA]
"""
import argparse
import csv
import json
import os
import time

ARQ = "yelp_academic_dataset_{}.json"


def campo(linha, nome, tamanho=22):
    """Extrai um id de 22 caracteres da linha sem fazer o parse do JSON inteiro."""
    chave = f'"{nome}":"'
    i = linha.find(chave)
    return linha[i + len(chave): i + len(chave) + tamanho] if i >= 0 else None


def limpo(texto):
    """Tira barra invertida e quebras de linha, que atrapalham o LOAD CSV do Neo4j."""
    return (texto or "").replace("\\", "/").replace("\n", " ").replace("\r", " ").strip()


def gravar(pasta, nome, cabecalho, linhas):
    caminho = os.path.join(pasta, nome)
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cabecalho)
        w.writerows(linhas)
    print(f"  {nome:<24} {len(linhas):>8} linhas  {os.path.getsize(caminho) / 1e6:6.1f} MB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("entrada")
    ap.add_argument("saida")
    ap.add_argument("--cidade", default="Santa Barbara")
    ap.add_argument("--estado", default="CA")
    a = ap.parse_args()
    os.makedirs(a.saida, exist_ok=True)
    t0 = time.time()
    abrir = lambda nome: open(os.path.join(a.entrada, ARQ.format(nome)), encoding="utf-8")

    # 1 · negócios da cidade
    negocios, categorias = {}, []
    for linha in abrir("business"):
        d = json.loads(linha)
        if d["city"].strip() != a.cidade or d["state"] != a.estado:
            continue
        preco = (d["attributes"] or {}).get("RestaurantsPriceRange2")
        negocios[d["business_id"]] = [
            d["business_id"], limpo(d["name"]), limpo(d["address"]), d["postal_code"],
            d["latitude"], d["longitude"], d["stars"], d["review_count"], d["is_open"],
            int(preco) if preco and preco.isdigit() else "", 0]      # o último é checkin_count
        for c in (d["categories"] or "").split(","):
            if c.strip():
                categorias.append([d["business_id"], c.strip()])
    print(f"[{time.time() - t0:4.0f}s] {len(negocios)} negócios em {a.cidade}, {a.estado}")

    # 2 · check-ins: só a contagem por negócio
    for linha in abrir("checkin"):
        d = json.loads(linha)
        if d["business_id"] in negocios:
            negocios[d["business_id"]][-1] = d["date"].count(",") + 1

    # 3 · reviews desses negócios, sem o texto
    reviews = []
    for linha in abrir("review"):
        if campo(linha, "business_id") not in negocios:
            continue
        d = json.loads(linha)
        reviews.append([d["review_id"], d["user_id"], d["business_id"], int(d["stars"]),
                        d["date"], d["useful"], d["funny"], d["cool"]])
    autores = {r[1] for r in reviews}
    print(f"[{time.time() - t0:4.0f}s] {len(reviews)} reviews de {len(autores)} usuários")

    # 4 · usuários que escreveram essas reviews; amizades só dentro do recorte
    usuarios, amizades = [], set()
    for linha in abrir("user"):
        uid = campo(linha, "user_id")
        if uid not in autores:
            continue
        d = json.loads(linha)
        usuarios.append([uid, limpo(d["name"]), d["review_count"], d["yelping_since"],
                         d["useful"], d["funny"], d["cool"], d["fans"], d["average_stars"]])
        if d["friends"] and d["friends"] != "None":
            for amigo in d["friends"].split(", "):
                if amigo in autores and amigo != uid:
                    amizades.add((uid, amigo) if uid < amigo else (amigo, uid))
    achados = {u[0] for u in usuarios}
    print(f"[{time.time() - t0:4.0f}s] {len(usuarios)} usuários encontrados, {len(amizades)} amizades")

    # 5 · integridade: reviews e amizades só de usuários que existem no arquivo de usuários
    sem_usuario = sum(1 for r in reviews if r[1] not in achados)
    reviews = [r for r in reviews if r[1] in achados]
    amizades = sorted(p for p in amizades if p[0] in achados and p[1] in achados)
    pares = sorted({(r[1], r[2]) for r in reviews})
    if sem_usuario:
        print(f"  aviso: {sem_usuario} reviews descartadas (autor ausente do arquivo de usuários)")

    print("arquivos gravados:")
    gravar(a.saida, "business.csv",
           ["business_id", "name", "address", "postal_code", "latitude", "longitude", "stars",
            "review_count", "is_open", "price_range", "checkin_count"], list(negocios.values()))
    gravar(a.saida, "business_category.csv", ["business_id", "category"], categorias)
    gravar(a.saida, "users.csv",
           ["user_id", "name", "review_count", "yelping_since", "useful", "funny", "cool", "fans",
            "average_stars"], usuarios)
    gravar(a.saida, "review.csv",
           ["review_id", "user_id", "business_id", "stars", "date", "useful", "funny", "cool"], reviews)
    gravar(a.saida, "friends.csv", ["user_a", "user_b"], amizades)
    gravar(a.saida, "reviewed.csv", ["user_id", "business_id"], pares)
    print(f"pronto em {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
