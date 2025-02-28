# Qt TS File Translator

This script processes Qt TS files, finds unfinished translations, and uses OpenAI to help translate them. The user can confirm, skip, edit, or quit for each translation.

## Requirements

- Python 3.6+
- Required Python packages (install using `pip install -r requirements.txt`):
  - requests
  - colorama

## Usage

```bash
python ts_translator.py path/to/your/file.ts --openai-token YOUR_OPENAI_TOKEN [options]
```

### Arguments

- `ts_file`: Path to the TS file to process (required)
- `--openai-url`: OpenAI API URL (default: https://api.openai.com/v1/chat/completions)
- `--openai-token`: OpenAI API token (required)
- `--openai-model`: OpenAI model to use (default: gpt-4o)
- `--debug`: Enable debug mode for detailed error information
- `--translate-empty`: Also translate empty translation elements (without type="unfinished")

### Example

```bash
# Translate only unfinished translations (default)
python ts_translator.py sample_test.ts --openai-token sk-your-token-here

# Translate both unfinished and empty translations
python ts_translator.py sample_test.ts --openai-token sk-your-token-here --translate-empty
```

For testing with a custom OpenAI URL:

```bash
python ts_translator.py sample_test.ts --openai-url https://api.proxyapi.ru/openai --openai-token sk-5EpnxBsXT7ISQzthbI1rwjUeCeXr6VC8
```

## Validating TS Files

Before translating, you can validate your TS file structure to ensure it's properly formatted:

```bash
python test_openai_connection.py --validate-ts path/to/your/file.ts
```

Or use the provided batch file:

```bash
validate_ts.bat
```

This will check for common issues in the TS file structure, such as:
- Missing context names
- Missing source elements
- Missing translation elements
- Empty text in required elements

## How It Works

1. The script parses the TS file and finds all unfinished translations (marked with `type="unfinished"`).
2. If the `--translate-empty` flag is used, it will also find empty translations (without the "unfinished" type).
3. For each translation to process, it sends a request to the OpenAI API with the source text, context, comment, and extracomment.
4. The OpenAI model provides a translation and an explanation of the translation choices.
5. The user is prompted to:
   - Accept the translation (`yes`)
   - Skip the translation (`no`)
   - Edit the translation (`edit`)
   - Quit the script (`quit`)
6. If the user accepts or edits the translation, the script updates the TS file and removes the `type="unfinished"` attribute if present.

## Error Handling

The script includes robust error handling for common issues:

- XML parsing errors with detailed traceback in debug mode
- Handling of missing or empty elements in the TS file
- Detailed API error reporting for OpenAI requests
- Graceful handling of user interruptions

If you encounter the error `'NoneType' object has no attribute 'text'`, enable debug mode with the `--debug` flag to get more detailed information about which element is causing the issue.

## Using in WSL

If you're using Windows Subsystem for Linux (WSL), you can run the script as follows:

```bash
# Install dependencies
pip install -r requirements.txt

# Run the script
python ts_translator.py sample_test.ts --openai-token YOUR_OPENAI_TOKEN
```

Make sure your default editor is set in the WSL environment by setting the `EDITOR` environment variable:

```bash
export EDITOR=nano  # or vim, emacs, etc.
```
