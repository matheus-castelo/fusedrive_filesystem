import os

MOUNT_DIR = "/home/castle/FuseDriveFilesystem"
TEST_FILE = os.path.join(MOUNT_DIR, "basic_test.txt")


def main():
    print("Iniciando testes básicos no FUSE...")

    # 1. ESCRITA (Criar arquivo)
    print(f"\n1. Escrevendo no arquivo: {TEST_FILE}")
    with open(TEST_FILE, "w") as f:
        f.write("Primeira linha - Arquivo de Teste.\n")
    print("✓ Escrita concluída.")

    # 2. LEITURA (Ler arquivo recém-criado)
    print(f"\n2. Lendo do arquivo: {TEST_FILE}")
    with open(TEST_FILE, "r") as f:
        content = f.read()
    print(f"Conteúdo lido:\n{content.strip()}")
    assert content == "Primeira linha - Arquivo de Teste.\n", "Erro na leitura."
    print("✓ Leitura concluída.")

    # 3. EDIÇÃO (Append no arquivo)
    print(f"\n3. Editando o arquivo (Append)...")
    with open(TEST_FILE, "a") as f:
        f.write("Segunda linha - Edição realizada com sucesso.\n")
    print("✓ Edição concluída.")

    # 4. LEITURA APÓS EDIÇÃO
    print(f"\n4. Lendo arquivo após edição...")
    with open(TEST_FILE, "r") as f:
        content = f.read()
    print(f"Conteúdo lido:\n{content.strip()}")
    expected = "Primeira linha - Arquivo de Teste.\nSegunda linha - Edição realizada com sucesso.\n"
    assert content == expected, "Erro na leitura após edição."
    print("✓ Leitura pós-edição validada com sucesso.")

    print("\nTODOS OS TESTES BÁSICOS PASSARAM!")


if __name__ == "__main__":
    main()
