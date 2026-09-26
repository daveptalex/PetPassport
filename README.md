# Pet Passport 1.0

Aplicação local-first em Python/Flet para gerir um passaporte digital completo de animais de companhia.

A mesma base de código destina-se a:

- Web/PWA;
- Android (APK/AAB);
- iOS (IPA, compilação em macOS/Xcode);
- desktop para desenvolvimento/testes.

## Funcionalidades incluídas

- Vários animais e seleção rápida do perfil ativo.
- Identificação, fotografia, espécie, raça, sexo, nascimento, peso e características.
- Dados de microchip.
- Tutor, contactos e contacto de emergência.
- Veterinário/clínica.
- Vacinas e destaque da vacinação antirrábica.
- Consultas veterinárias.
- Medicação e histórico de tomas.
- Peso e histórico cronológico.
- Desparasitação.
- Alergias e condições médicas.
- Cirurgias e exames.
- Seguro.
- Viagens e checklist documental.
- Lembretes internos.
- Biblioteca de documentos e anexos.
- Timeline consolidada.
- Pesquisa universal.
- QR de emergência/offline.
- Modo animal perdido.
- Modo de emergência.
- Exportação PDF por animal.
- Exportação CSV.
- Exportação JSON.
- Backup ZIP portátil com anexos, JSON, CSV e PDF.
- Importação/restauro do backup ZIP.
- PIN com PBKDF2.
- Autenticação biométrica quando suportada pela plataforma.
- SecureStorage para os dados estruturados.
- Anexos no diretório privado da app em Android/iOS/desktop.
- Tema claro, escuro ou automático.
- Sem conta obrigatória e sem servidor obrigatório.

## Requisitos

- Python 3.10 ou superior para desenvolvimento.
- Os scripts de build usam Python 3.12 para a app empacotada.
- Ligação à Internet na primeira instalação das dependências e durante builds que precisem de toolchains.

## Instalação rápida — Linux/macOS

```bash
chmod +x setup.sh run_web.sh run_desktop.sh build_android.sh build_web.sh build_ios.sh
./setup.sh
```

### Executar como web app

```bash
./run_web.sh
```

### Executar como app desktop para testes

```bash
./run_desktop.sh
```

### Android

APK + AAB:

```bash
./build_android.sh
```

Os artefactos ficam na pasta `build/` criada pelo Flet.

### Web/PWA

```bash
./build_web.sh
```

O build Web usa o modo `--no-cdn`, pelo que os recursos do runtime são incluídos no próprio build para reduzir dependências externas e permitir funcionamento offline depois de carregada/instalada a PWA.

### iOS

A compilação IPA requer macOS com Xcode instalado:

```bash
./build_ios.sh
```

## Windows

Primeira instalação:

```bat
setup_windows.bat
```

Web:

```bat
run_web_windows.bat
```

Android:

```bat
build_android_windows.bat
```

Web/PWA offline:

```bat
build_web_windows.bat
```

## Estrutura

```text
PetPassport/
├── src/
│   ├── main.py
│   ├── core.py
│   └── assets/
│       ├── icon.png
│       └── splash.png
├── tests/
│   └── test_core.py
├── pyproject.toml
├── requirements.txt
├── setup.sh
├── run_web.sh
├── run_desktop.sh
├── build_android.sh
├── build_web.sh
├── build_ios.sh
├── setup_windows.bat
├── run_web_windows.bat
├── build_web_windows.bat
└── build_android_windows.bat
```

## Armazenamento e privacidade

Os registos estruturados são gravados no SecureStorage do Flet. Nas aplicações instaladas, os anexos são copiados para o diretório privado de dados da aplicação. Na versão web, os anexos são guardados dentro do estado local e existe um limite deliberadamente mais baixo de 1,5 MB por ficheiro para reduzir problemas de quota no browser.

O backup ZIP é portátil: inclui o estado completo, cópias dos anexos, CSV e relatórios PDF. Um restauro numa app instalada materializa novamente os anexos no armazenamento privado da aplicação.

## QR de emergência

O QR desta versão é deliberadamente offline. Em vez de depender de um servidor público, contém apenas os dados que o utilizador escolheu disponibilizar para emergência/animal perdido, e pode ser lido por um scanner QR comum.

Uma página pública por URL exigiria um backend/hosting e deixa de ser uma solução integralmente local-first. Pode ser acrescentada posteriormente como módulo opcional.

## Lembretes

Os lembretes desta versão aparecem dentro da aplicação e no dashboard. Agendamento de notificações locais em background ao nível do sistema operativo não foi incluído porque requer integração nativa adicional por plataforma.

## Segurança

O PIN nunca é guardado em texto simples. É derivado com PBKDF2-HMAC-SHA256 e salt aleatório. A autenticação biométrica usa a API disponível através da extensão Flet Local Authentication.

O conteúdo do QR deve ser tratado como público: qualquer pessoa que possua o QR pode ler os campos nele codificados.

## Testes

Depois de instalar as dependências:

```bash
python -m unittest discover -s tests -v
```

## Aviso veterinário

Esta aplicação organiza informação fornecida pelo tutor e por documentos associados. Não efetua diagnóstico e não substitui aconselhamento veterinário profissional.

## GitHub Actions — APK/AAB na cloud

Esta edição inclui um workflow pronto em:

```text
.github/workflows/build-android.yml
```

No GitHub, abra **Actions → Pet Passport - Android APK e AAB → Run workflow** e escolha `both`, `apk` ou `aab`.

O workflow executa os testes, compila com a action oficial `flet-dev/flet-build-action@v1` e guarda os resultados como artefactos descarregáveis. Consulte `GUIA_GITHUB_ACTIONS.txt` para as instruções completas, incluindo o processo alternativo para criar manualmente a pasta `.github` caso o gestor de ficheiros Android a esconda.

Sem uma upload keystore própria, os builds Android de release são assinados com a chave de debug do Flet/Flutter, adequada para testes e instalação direta, mas não para publicação final na Google Play Store.
