#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Qt TS File Translator

This script processes Qt TS files, finds unfinished translations, and uses OpenAI
to help translate them. The user can confirm, skip, edit, or quit for each translation.
With the --cache-only option the script runs without prompting the user or modifying the TS file,
and only fills the OpenAI response cache.
Additionally, you can specify context name prefixes (using --skip-context-prefixes)
to skip translation for certain contexts.
"""

import argparse
import os
import sys
import xml.etree.ElementTree as ET
import requests
import json
import subprocess
import tempfile
import traceback
import pickle
import re
from colorama import init, Fore, Style

# Initialize colorama for colored console output
init()

# Cache filename for storing OpenAI responses
CACHE_FILENAME = "openai_cache.pkl"

def load_cache(filename):
    """Load the cache from a pickle file."""
    if os.path.exists(filename):
        try:
            with open(filename, "rb") as f:
                cache = pickle.load(f)
                return cache
        except Exception as e:
            print(f"{Fore.RED}Error loading cache: {e}{Style.RESET_ALL}")
            return {}
    return {}

def save_cache(cache, filename):
    """Save the cache to a pickle file."""
    try:
        with open(filename, "wb") as f:
            pickle.dump(cache, f)
    except Exception as e:
        print(f"{Fore.RED}Error saving cache: {e}{Style.RESET_ALL}")

def write_ts_file(tree, ts_file):
    xml_str = ET.tostring(tree.getroot(), encoding='utf-8').decode('utf-8')
    with open(ts_file, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE TS>\n' + xml_str)

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Translate unfinished translations in Qt TS files using OpenAI.')
    parser.add_argument('ts_file', help='Path to the TS file to process')
    parser.add_argument('--openai-url', default='https://api.openai.com/v1/chat/completions',
                        help='OpenAI API URL (default: https://api.openai.com/v1/chat/completions)')
    parser.add_argument('--openai-token', required=True, help='OpenAI API token')
    parser.add_argument('--openai-model', default='gpt-4o', help='OpenAI model to use (default: gpt-4o)')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--translate-empty', action='store_true', 
                        help='Also translate empty translation elements (without type="unfinished")')
    parser.add_argument('--skip-ui', action='store_true',
                        help='Skip translations located in UI files')
    parser.add_argument('--additional-prompt-file', help='Path to file with additional prompt text', default=None)
    parser.add_argument('--cache-only', action='store_true',
                        help='Run without asking user or modifying TS file; only fill the OpenAI response cache')
    parser.add_argument('--skip-context-prefixes', default="",
                        help='Comma-separated list of context name prefixes to skip and not translate')
    parser.add_argument('--translate-non-english-source', action='store_true',
                        help='Detect and translate non-English source text to English (without modifying the TS file)')
    return parser.parse_args()

def get_target_language(root):
    """Extract target language from TS file."""
    language = root.get('language', '')
    if not language:
        print(f"{Fore.RED}Error: Could not determine target language from TS file.{Style.RESET_ALL}")
        sys.exit(1)
    return language

def translate_text(source_text, context_name, comment, extracomment, 
                  target_language=None, to_english=False,
                  openai_url=None, openai_token=None, openai_model=None, 
                  additional_prompt=None, cache=None, debug=False):
    """
    Translate text using OpenAI API with caching.
    
    Args:
        source_text: The text to translate
        context_name: The context name from the TS file
        comment: The comment from the TS file
        extracomment: The extracomment from the TS file
        target_language: The target language code (e.g., 'ru_RU') - used when not translating to English
        to_english: If True, translate to English regardless of target_language
        openai_url: The OpenAI API URL
        openai_token: The OpenAI API token
        openai_model: The OpenAI model to use
        additional_prompt: Extra prompt content loaded from file
        cache: Dictionary for caching responses
        debug: Whether to print debug information
        
    Returns:
        tuple: (translated_text, explanation, confidence)
    """
    # Ensure the OpenAI URL ends with /chat/completions
    if not openai_url.endswith('/chat/completions'):
        if openai_url.endswith('/'):
            openai_url = openai_url + 'chat/completions'
        else:
            openai_url = openai_url + '/chat/completions'
        if debug:
            print(f"{Fore.CYAN}Updated OpenAI URL to: {openai_url}{Style.RESET_ALL}")
    
    # Determine the language name from the language code
    language_map = {
        'ru_RU': 'Russian',
        'en_US': 'English',
        'fr_FR': 'French',
        'de_DE': 'German',
        'es_ES': 'Spanish',
        'it_IT': 'Italian',
        'zh_CN': 'Chinese (Simplified)',
        'ja_JP': 'Japanese',
        # Add more languages as needed
    }
    
    # Set up translation direction
    if to_english:
        target_language_name = "English"
        # Create a special cache key for source-to-English translations
        key = ("source_to_english", source_text, context_name, comment, extracomment, additional_prompt, openai_model, openai_url)
    else:
        target_language_name = language_map.get(target_language, target_language)
        # Create a cache key based on the inputs for normal translations
        key = (source_text, context_name, comment, extracomment, target_language, additional_prompt, openai_model, openai_url)
    
    if key in cache:
        if debug:
            print(f"{Fore.CYAN}Cache hit for {'source-to-English' if to_english else 'normal'} translation.{Style.RESET_ALL}")
        return cache[key]
    
    # Prepare the prompt for OpenAI
    system_prompt = f"You are a professional translator to {target_language_name}."
    
    if to_english:
        prompt_intro = f"Translate the provided source text to English."
    else:
        prompt_intro = f"Translate the provided source text from the source language to {target_language_name}."
    
    prompt = f"""
{prompt_intro}
Consider the context, comment, and extracomment provided.

{additional_prompt}

Please provide:
1. The translation in {target_language_name}
2. A brief explanation of your translation choices
3. A confidence score (from 0 to 100) indicating your confidence in the translation

If the source text is a multiline passage, please preserve its original line breaks and translate each line accordingly.
If the source text appears to already be in {target_language_name}, return source text as is, indicate 0 confidence and an explanation that the text is already in the target language.
If the source text contains placeholders such as %1, %2, %3, etc., ensure these placeholders are preserved in the translated text in the correct position so that the meaning remains consistent.

Format your response exactly as:
TRANSLATION: [your translation]
EXPLANATION: [your explanation]
CONFIDENCE_PERCENTAGE: [your confidence percentage without % sign]
END_RESPONSE

Input is following:
Source text: {source_text}
Context: {context_name}
Comment: {comment}
Extracomment: {extracomment}
"""
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {openai_token}'
    }
    
    data = {
        'model': openai_model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': prompt}
        ],
        'temperature': 0.3
    }
    
    try:
        if debug:
            print(f"{Fore.CYAN}Debug - OpenAI URL: {openai_url}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}Debug - OpenAI Model: {openai_model}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}Debug - Headers: {headers}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}Debug - Data: {json.dumps(data, indent=2)}{Style.RESET_ALL}")
        
        response = requests.post(openai_url, headers=headers, data=json.dumps(data))
        
        if debug:
            print(f"{Fore.CYAN}Debug - Response Status Code: {response.status_code}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}Debug - Response Headers: {response.headers}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}Debug - Response Content: {response.text}{Style.RESET_ALL}")
        
        response.raise_for_status()
        
        result = response.json()
        content = result['choices'][0]['message']['content']
        
        # Use regular expressions to capture potentially multiline output.
        match = re.search(r"TRANSLATION:\s*(.*?)\s*EXPLANATION:\s*(.*?)\s*CONFIDENCE_PERCENTAGE:\s*(.*?)\s*END_RESPONSE", content, re.DOTALL)
        if match:
            if debug:
                print(f"{Fore.CYAN}Debug - Match: {match.group(1).strip()} {match.group(2).strip()} {match.group(3).strip()}{Style.RESET_ALL}")
            
            translation_text = match.group(1).strip()
            explanation_text = match.group(2).strip()
            confidence_text = match.group(3).strip()
        else:
            # Fallback if expected markers are not found:
            if debug:
                print(f"{Fore.CYAN}Debug - No match found{Style.RESET_ALL}")

            paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
            translation_text = paragraphs[0] if paragraphs else ""
            explanation_text = paragraphs[1] if len(paragraphs) > 1 else ""
            confidence_text = paragraphs[2] if len(paragraphs) > 2 else ""
        
        if debug:
            print(f"{Fore.CYAN}Debug - Translation text: {translation_text}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}Debug - Explanation text: {explanation_text}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}Debug - Confidence text: {confidence_text}{Style.RESET_ALL}")
        
        # Cache the result and save to file
        cache[key] = (translation_text, explanation_text, confidence_text)
        save_cache(cache, CACHE_FILENAME)
        return translation_text, explanation_text, confidence_text
        
    except requests.exceptions.RequestException as e:
        print(f"{Fore.RED}Error calling OpenAI API: {str(e)}{Style.RESET_ALL}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"{Fore.RED}Response status code: {e.response.status_code}{Style.RESET_ALL}")
            print(f"{Fore.RED}Response content: {e.response.text}{Style.RESET_ALL}")
        return None, None, None
    except Exception as e:
        print(f"{Fore.RED}Unexpected error: {str(e)}{Style.RESET_ALL}")
        return None, None, None

def edit_translation(translation):
    """Open the default editor to edit the translation."""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode='w', encoding='utf-8') as temp:
        temp.write(translation)
        temp_filename = temp.name
    
    # Determine the editor to use
    editor = os.environ.get('EDITOR', 'nano')
    
    try:
        subprocess.run([editor, temp_filename], check=True)
        with open(temp_filename, 'r', encoding='utf-8') as temp:
            edited_translation = temp.read().strip()
        os.unlink(temp_filename)
        return edited_translation
    except Exception as e:
        print(f"{Fore.RED}Error opening editor: {str(e)}{Style.RESET_ALL}")
        os.unlink(temp_filename)
        return translation

def should_translate_element(translation_elem, translate_empty=False):
    """
    Determine if a translation element should be translated.
    
    Args:
        translation_elem: The translation element from the TS file
        translate_empty: Whether to translate empty translation elements
        
    Returns:
        bool: True if the element should be translated, False otherwise
    """
    # Check if this is an unfinished translation
    is_unfinished = translation_elem.get('type') == 'unfinished'
    
    # Check if this is an empty translation
    is_empty = translation_elem.text is None or translation_elem.text.strip() == ""
    
    # Translate if it's unfinished or (it's empty and translate_empty is True)
    return is_unfinished or (is_empty and translate_empty)

def process_ts_file(ts_file, openai_url, openai_token, openai_model, additional_prompt,
                    cache, debug=False, translate_empty=False, skip_ui=False, cache_only=False, skip_context_prefixes=None,
                    translate_non_english_source=False):
    """Process the TS file and translate unfinished translations."""
    try:
        # Parse the TS file
        tree = ET.parse(ts_file)
        root = tree.getroot()
        
        # Get target language
        target_language = get_target_language(root)
        print(f"{Fore.CYAN}Target language: {target_language}{Style.RESET_ALL}")
        
        # Find all messages with unfinished translations
        unfinished_count = 0
        empty_count = 0
        processed_count = 0
        non_english_source_count = 0
        
        # Iterate through all contexts
        # Process comma-separated context prefixes into a list
        if skip_context_prefixes:
            prefixes = [p.strip() for p in skip_context_prefixes.split(',') if p.strip()]
        else:
            prefixes = []
        
        for context in root.findall('.//context'):
            # Get context name with error handling
            context_name_elem = context.find('name')
            if context_name_elem is None:
                if debug:
                    print(f"{Fore.RED}Debug - Warning: Found context without a name element, skipping.{Style.RESET_ALL}")
                continue
                
            context_name = context_name_elem.text
            if context_name is None:
                if debug:
                    print(f"{Fore.RED}Debug - Warning: Found context with empty name, using empty string.{Style.RESET_ALL}")
                context_name = ""
            elif any(context_name.startswith(prefix) for prefix in prefixes):
                if debug:
                    print(f"{Fore.CYAN}Skipping context '{context_name}' due to skip-context-prefixes setting.{Style.RESET_ALL}")
                continue

            if debug:
                print(f"{Fore.CYAN}Debug - Processing context: {context_name}{Style.RESET_ALL}")
            
            # Iterate through all messages in the context
            for message in context.findall('message'):
                # If --skip-ui is enabled, skip messages with location filenames ending with ".ui"
                if skip_ui:
                    location_elems = message.findall('location')
                    if any(loc.attrib.get('filename', '').lower().endswith('.ui') for loc in location_elems):
                        if debug:
                            for loc in location_elems:
                                if loc.attrib.get('filename', '').lower().endswith('.ui'):
                                    print(f"{Fore.CYAN}Skipping UI file translation for message in context '{context_name}' at location {loc.attrib.get('filename','')}:{loc.attrib.get('line','')}{Style.RESET_ALL}")
                        continue

                translation_elem = message.find('translation')
                
                # Check if translation element exists
                if translation_elem is None:
                    if debug:
                        print(f"{Fore.RED}Debug - Warning: Found message without translation element in context '{context_name}', skipping.{Style.RESET_ALL}")
                    continue
                
                # Check if this element should be translated
                if should_translate_element(translation_elem, translate_empty):
                    # Count the type of translation
                    if translation_elem.get('type') == 'unfinished':
                        unfinished_count += 1
                    else:
                        empty_count += 1
                    
                    # Get source text and comments with error handling
                    source_elem = message.find('source')
                    if source_elem is None:
                        if debug:
                            print(f"{Fore.RED}Debug - Warning: Found message without source element in context '{context_name}', skipping.{Style.RESET_ALL}")
                        continue
                    
                    source_text = source_elem.text
                    if source_text is None:
                        if debug:
                            print(f"{Fore.RED}Debug - Warning: Found message with empty source in context '{context_name}', using empty string.{Style.RESET_ALL}")
                        source_text = ""
                    
                    comment_elem = message.find('comment')
                    comment_text = comment_elem.text if comment_elem is not None and comment_elem.text is not None else ""
                    
                    extracomment_elem = message.find('extracomment')
                    extracomment_text = extracomment_elem.text if extracomment_elem is not None and extracomment_elem.text is not None else ""
                    
                    print(f"\n{Fore.YELLOW}{'='*80}{Style.RESET_ALL}")
                    # If location elements are specified, print them
                    location_elems = message.findall('location')
                    for loc in location_elems:
                        filename = loc.attrib.get('filename', '')
                        line_no = loc.attrib.get('line', '')
                        # Transform location path relatively to ts file directory
                        if filename:
                            # Get the directory of the TS file
                            ts_file_dir = os.path.dirname(os.path.abspath(ts_file))
                            
                            # Try to make the path absolute relative to the TS file directory
                            try:
                                # If the filename is not already absolute
                                if not os.path.isabs(filename):
                                    # Make it absolute by joining with the TS file directory
                                    abs_path = os.path.normpath(os.path.join(ts_file_dir, filename))
                                    if debug:
                                        print(f"{Fore.CYAN}Transformed relative path '{filename}' to absolute path '{abs_path}'{Style.RESET_ALL}")
                                    filename = abs_path
                            except Exception as e:
                                if debug:
                                    print(f"{Fore.RED}Error transforming path: {e}{Style.RESET_ALL}")
                        
                        if filename:
                            print(f"{Fore.BLUE}Location:{Style.RESET_ALL} {filename}:{line_no}")
                    
                    print(f"{Fore.GREEN}Context:{Style.RESET_ALL} {context_name}")
                    print(f"{Fore.GREEN}Source:{Style.RESET_ALL} {source_text}")
                    
                    # If translate_non_english_source is enabled, check if source text needs translation to English
                    if translate_non_english_source and source_text.strip():
                        # Translate source text to English
                        english_source, explanation, confidence = translate_text(
                            source_text, context_name, comment_text, extracomment_text,
                            None, True, openai_url, openai_token, openai_model, additional_prompt, cache, debug
                        )
                        
                        # Only show confidence in debug mode
                        if debug:
                            print(f"{Fore.GREEN}Confidence:{Style.RESET_ALL} {confidence}")

                        # Check if the source was actually non-English (confidence > 0)
                        if confidence and float(confidence.strip().rstrip('%').strip()) > 0:
                            non_english_source_count += 1
                            print(f"{Fore.MAGENTA}Non-English source detected!{Style.RESET_ALL}")
                            print(f"{Fore.MAGENTA}English translation:{Style.RESET_ALL} {english_source}")
                            if explanation:
                                print(f"{Fore.MAGENTA}Explanation:{Style.RESET_ALL} {explanation}")
                            if confidence:
                                print(f"{Fore.MAGENTA}Confidence:{Style.RESET_ALL} {confidence}")
                            
                            # Skip the rest of the processing for this message  
                            continue
                    
                    if comment_text:
                        print(f"{Fore.GREEN}Comment:{Style.RESET_ALL} {comment_text}")
                    if extracomment_text:
                        print(f"{Fore.GREEN}Extracomment:{Style.RESET_ALL} {extracomment_text}")
                    
                    # Current translation (if any)
                    current_translation = translation_elem.text or ""
                    if current_translation:
                        if translation_elem.get('type') == 'unfinished':
                            print(f"{Fore.GREEN}Current unfinished translation:{Style.RESET_ALL} {current_translation}")
                        else:
                            print(f"{Fore.GREEN}Current empty translation:{Style.RESET_ALL} {current_translation}")
                    
                    # Translate using OpenAI with caching
                    if debug:
                        print(f"{Fore.CYAN}Translating...{Style.RESET_ALL}")
                    
                    translated_text, explanation, confidence = translate_text(
                        source_text, context_name, comment_text, extracomment_text,
                        target_language, False, openai_url, openai_token, openai_model,
                        additional_prompt, cache, debug
                    )
                    
                    # If source text is missing (i.e. only "..." or "…"), move the error message to explanation and set confidence to 0.
                    if source_text.strip() in ["...", "…"]:
                        explanation = translated_text
                        translated_text = ""
                        confidence = "0"
                    
                    if explanation:
                        print(f"{Fore.GREEN}Explanation:{Style.RESET_ALL} {explanation}")
                    if confidence:
                        print(f"{Fore.GREEN}Confidence:{Style.RESET_ALL} {confidence}")
                    if translated_text:
                        print(f"{Fore.GREEN}Translated text:{Style.RESET_ALL} {translated_text}")
                    
                    # Ask for user confirmation
                    if not cache_only:
                        # Ask for user confirmation if not in cache-only mode
                        if confidence and float(confidence.strip().rstrip('%').strip()) < 10:
                            print(f"{Fore.CYAN}Confidence is 0%, automatically skipping this translation.{Style.RESET_ALL}")
                        else:
                            while True:
                                if not translated_text and explanation.startswith("I'm sorry, but it seems"):
                                    prompt_str = f"{Fore.YELLOW}Accept this translation? (no/edit/quit): {Style.RESET_ALL}"
                                    valid_choices = {'no', 'n', 'edit', 'e', 'quit', 'q'}
                                else:
                                    prompt_str = f"{Fore.YELLOW}Accept this translation? (yes/no/edit/quit): {Style.RESET_ALL}"
                                    valid_choices = {'yes', 'y', 'no', 'n', 'edit', 'e', 'quit', 'q'}
                                
                                choice = input(prompt_str).lower()
                                
                                if choice not in valid_choices:
                                    print(f"{Fore.RED}Invalid choice. Please enter one of {', '.join(valid_choices)}.{Style.RESET_ALL}")
                                    continue
                                
                                if choice in ('yes', 'y'):
                                    translation_elem.text = translated_text
                                    if 'type' in translation_elem.attrib:
                                        translation_elem.attrib.pop('type', None)
                                    processed_count += 1
                                    break
                                elif choice in ('no', 'n'):
                                    print(f"{Fore.CYAN}Skipping this translation.{Style.RESET_ALL}")
                                    break
                                elif choice in ('edit', 'e'):
                                    edited_translation = edit_translation(translated_text)
                                    print(f"{Fore.GREEN}Edited translation:{Style.RESET_ALL} {edited_translation}")
                                    
                                    confirm_edit = input(f"{Fore.YELLOW}Use this edited translation? (yes/no): {Style.RESET_ALL}").lower()
                                    if confirm_edit in ('yes', 'y'):
                                        translation_elem.text = edited_translation
                                        if 'type' in translation_elem.attrib:
                                            translation_elem.attrib.pop('type', None)
                                        processed_count += 1
                                        break
                                elif choice in ('quit', 'q'):
                                    print(f"{Fore.CYAN}Quitting...{Style.RESET_ALL}")
                                    write_ts_file(tree, ts_file)
                                    print(f"{Fore.GREEN}Saved {processed_count} translations out of {unfinished_count + empty_count} total translations.{Style.RESET_ALL}")
                                    return
                    else:
                        processed_count += 1
        
        if not cache_only:
            write_ts_file(tree, ts_file)
            print(f"\n{Fore.GREEN}Completed! Processed {processed_count} out of {unfinished_count + empty_count} total translations.{Style.RESET_ALL}")
            if translate_empty:
                print(f"{Fore.GREEN}Details: {unfinished_count} unfinished translations, {empty_count} empty translations.{Style.RESET_ALL}")
            if translate_non_english_source:
                print(f"{Fore.GREEN}Found {non_english_source_count} non-English source texts that were translated to English.{Style.RESET_ALL}")
        else:
            print(f"\n{Fore.GREEN}Cache-only mode complete. Processed {processed_count} translations without modifying the TS file.{Style.RESET_ALL}")
            if translate_non_english_source:
                print(f"{Fore.GREEN}Found {non_english_source_count} non-English source texts that were translated to English.{Style.RESET_ALL}")
        
    except ET.ParseError as e:
        print(f"{Fore.RED}Error parsing TS file: {str(e)}{Style.RESET_ALL}")
        if debug:
            print(f"{Fore.RED}Debug - XML Parse Error Details:{Style.RESET_ALL}")
            traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"{Fore.RED}Error processing TS file: {str(e)}{Style.RESET_ALL}")
        if debug:
            print(f"{Fore.RED}Debug - Error Details:{Style.RESET_ALL}")
            traceback.print_exc()
        sys.exit(1)

def main():
    """Main function."""
    args = parse_arguments()
    
    # Load additional prompt from file if provided
    additional_prompt = ""
    if args.additional_prompt_file:
        if os.path.isfile(args.additional_prompt_file):
            with open(args.additional_prompt_file, 'r', encoding='utf-8') as f:
                additional_prompt = f.read()
        else:
            print(f"{Fore.RED}Error: Additional prompt file '{args.additional_prompt_file}' not found.{Style.RESET_ALL}")
            sys.exit(1)
    
    # Load the cache from file
    cache = load_cache(CACHE_FILENAME)
    
    # Check if the TS file exists
    if not os.path.isfile(args.ts_file):
        print(f"{Fore.RED}Error: TS file '{args.ts_file}' not found.{Style.RESET_ALL}")
        sys.exit(1)
    
    print(f"{Fore.CYAN}Processing TS file: {args.ts_file}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Using OpenAI model: {args.openai_model}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Using OpenAI URL: {args.openai_url}{Style.RESET_ALL}")
    
    if args.translate_empty:
        print(f"{Fore.CYAN}Will translate both unfinished and empty translations{Style.RESET_ALL}")
    else:
        print(f"{Fore.CYAN}Will translate only unfinished translations (use --translate-empty to include empty translations){Style.RESET_ALL}")
    
    if args.skip_ui:
        print(f"{Fore.CYAN}Skipping translations from UI files{Style.RESET_ALL}")
    
    if args.cache_only:
        print(f"{Fore.CYAN}Running in cache-only mode: TS file will not be modified and no user input will be requested.{Style.RESET_ALL}")
    
    if args.translate_non_english_source:
        print(f"{Fore.CYAN}Will detect and translate non-English source text to English (without modifying the TS file){Style.RESET_ALL}")
    
    # Process the TS file with the loaded additional prompt and cache
    if args.skip_context_prefixes:
        print(f"{Fore.CYAN}Skipping contexts with prefixes: {args.skip_context_prefixes}{Style.RESET_ALL}")
    
    process_ts_file(args.ts_file, args.openai_url, args.openai_token, args.openai_model,
                    additional_prompt, cache, debug=args.debug, translate_empty=args.translate_empty,
                    skip_ui=args.skip_ui, cache_only=args.cache_only, skip_context_prefixes=args.skip_context_prefixes,
                    translate_non_english_source=args.translate_non_english_source)

if __name__ == "__main__":
    main()
