# Fuse+Drive

O **Fuse+Drive** é um sistema de arquivos virtual (VFS) construído com a interface FUSE que permite montar pastas do Google Drive diretamente no seu sistema operacional local. Com foco em alta performance e utilização eficiente de cache local, ele fornece uma experiência nativa e fluida para manipulação de arquivos na nuvem.

## Pré-requisitos

Para executar este projeto, seu sistema operacional Linux deve possuir suporte à biblioteca FUSE3.

- **Arch Linux / CachyOS**:
  ```bash
  sudo pacman -S fuse3
  ```

- **Ubuntu / Debian**:
  ```bash
  sudo apt install fuse3 libfuse3-dev
  ```

- **Windows (WSL2)**:
  O WSL2 possui suporte nativo ao FUSE. Instale as dependências padrão do Ubuntu/Debian no seu terminal WSL:
  ```bash
  sudo apt install fuse3 libfuse3-dev
  ```
  Para acessar os arquivos mapeados diretamente no Windows Explorer, basta navegar até a rede do WSL. Exemplo: `\\wsl$\Ubuntu\home\seu_usuario\Fuse+Drive\mount_dir` ou `\\wsl.localhost\Ubuntu\...`.

## Configuração

### 1. Obtendo as Credenciais da API do Google Drive
Para permitir que o sistema acesse o Google Drive, você precisará gerar credenciais de acesso no Google Cloud Console. Siga os passos abaixo detalhadamente:

1. Acesse o [Google Cloud Console](https://console.cloud.google.com/).
2. Crie um novo projeto ou selecione um existente.
3. No menu de navegação, acesse **APIs e Serviços > Biblioteca** e busque por "Google Drive API". Clique em **Ativar**.
4. Acesse **APIs e Serviços > Tela de consentimento OAuth** e configure-a preenchendo as informações básicas solicitadas.
5. Em seguida, vá em **APIs e Serviços > Credenciais**, clique em **Criar Credenciais** e selecione a opção **ID do cliente OAuth**.
6. Selecione o tipo de aplicativo como **App de computador** (Desktop App) e clique em criar. (Alternativamente, você pode criar uma **Conta de Serviço / Service Account**).
7. Faça o download do arquivo JSON gerado com suas chaves. Renomeie este arquivo para `credentials.json` e coloque-o na raiz deste projeto.
8. **Atenção ao Compartilhamento:** Se você utilizou uma Conta de Serviço (Service Account), o Google Cloud gerou um endereço de e-mail associado a ela (ex: `app@projeto.iam.gserviceaccount.com`). Você **deve** abrir o Google Drive pelo navegador e compartilhar a pasta desejada com esse e-mail, concedendo permissões de Leitura/Escrita para que o FUSE possa enxergá-la.

> **⚠️ IMPORTANTE: Diferença entre os tipos de Credenciais**
> - **App de Computador (OAuth 2.0)**: **Altamente Recomendado.** O sistema abrirá uma janela no seu navegador solicitando que você faça login com a sua própria conta Google. Com isso, os uploads consumirão o **seu espaço de armazenamento pessoal**, evitando erros de cota esgotada.
> - **Conta de Serviço (Service Account)**: O Google cria um "bot" com um e-mail próprio. Se você compartilhar sua pasta do Drive com esse e-mail, **ele funcionará perfeitamente para Leitura/Download**. Porém, **NÃO funcionará para Escrita/Upload**. Como bots em planos gratuitos possuem 0 bytes de cota, tentativas de upload resultarão no erro `403 storageQuotaExceeded`, mesmo que a pasta compartilhada tenha espaço de sobra. Utilize esta opção **apenas** para leitura ou se a pasta alvo estiver em um Drive Compartilhado (Shared Drive) de um plano corporativo Workspace.

### 2. Variáveis de Ambiente (.env)
O sistema carrega todas as suas configurações dinamicamente. Para configurá-lo, crie um arquivo chamado `.env` na raiz do projeto contendo as seguintes variáveis:

```ini
# Configurações Principais
DRIVE_CREDENTIALS=credentials.json
DRIVE_FOLDER_ID=COLOQUE_AQUI_O_ID_DA_SUA_PASTA
DRIVE_MOUNT_DIR=mount_dir

# Permissões Opcionais (Controle Unix)
PUID=1000
PGID=1000
FUSE_ALLOW_OTHER=0
```

> **Dica**: O `DRIVE_FOLDER_ID` pode ser encontrado na URL do seu navegador ao abrir a pasta desejada no Google Drive (ex: `https://drive.google.com/drive/folders/ESTE_EH_O_ID`).

O diretório definido na variável `DRIVE_MOUNT_DIR` (por padrão, a pasta `mount_dir`) será criado automaticamente pelo sistema durante a montagem caso ainda não exista.

## Como Executar (Localmente)

Recomendamos o uso do gerenciador de ambientes `uv` para instalar as dependências de forma isolada.

1. Configure o ambiente virtual e instale as dependências automaticamente:
   ```bash
   make setup
   ```

2. Ative o ambiente virtual para que o seu terminal reconheça os pacotes:
   ```bash
   source .venv/bin/activate
   ```

3. Limpe montagens pendentes e inicie a montagem do disco (o processo ficará atrelado ao terminal):
   ```bash
   make clean
   uv run python -m src.main
   ```

4. Para parar a execução nativa e desmontar:
   - Pressione `Ctrl+C` no terminal onde o processo está rodando.
   - Caso o diretório fique travado (mount zumbi), basta forçar a limpeza em outro terminal com:
     ```bash
     make clean
     ```

## Como Executar (via Docker)j

Se preferir rodar o serviço isolado sem instalar dependências do Python no seu sistema host, você pode usar o Docker Compose.

1. Construa a imagem e inicie o serviço em background:
   ```bash
   make build
   make up
   ```

2. Para acompanhar a execução e os logs em tempo real:
   ```bash
   docker compose logs -f
   ```

3. Para desmontar e desligar o sistema:
   ```bash
   make down
   ```

## Testes

O projeto assegura sua confiabilidade mantendo uma cobertura mínima de testes de 80%. Para executar toda a suíte de testes automatizados:

```bash
pytest tests/
```
