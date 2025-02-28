#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Qt TS File Translator

This script processes Qt TS files, finds unfinished translations, and uses OpenAI
to help translate them. The user can confirm, skip, edit, or quit for each translation.
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
from colorama import init, Fore, Style

# Initialize colorama for colored console output
init()

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
    return parser.parse_args()

def get_target_language(root):
    """Extract target language from TS file."""
    language = root.get('language', '')
    if not language:
        print(f"{Fore.RED}Error: Could not determine target language from TS file.{Style.RESET_ALL}")
        sys.exit(1)
    return language

def translate_with_openai(source_text, context_name, comment, extracomment, target_language, openai_url, openai_token, openai_model, debug=False):
    """
    Translate text using OpenAI API.
    
    Args:
        source_text: The text to translate
        context_name: The context name from the TS file
        comment: The comment from the TS file
        extracomment: The extracomment from the TS file
        target_language: The target language code (e.g., 'ru_RU')
        openai_url: The OpenAI API URL
        openai_token: The OpenAI API token
        openai_model: The OpenAI model to use
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
    
    target_language_name = language_map.get(target_language, target_language)
    
    # Prepare the prompt for OpenAI
    prompt = f"""
Translate the following text from the source language to {target_language_name}.
Consider the context, comment, and extracomment provided.

Source text: {source_text}
Context: {context_name}
Comment: {comment}
Extracomment: {extracomment}

Please provide:
1. The translation in {target_language_name}
2. A brief explanation of your translation choices
3. A confidence score (from 0 to 100%) indicating your confidence in the translation

Format your response as:
TRANSLATION: [your translation]
EXPLANATION: [your explanation]
CONFIDENCE: [your confidence percentage]
"""
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {openai_token}'
    }
    
    data = {
        'model': openai_model,
        'messages': [
            {'role': 'system', 'content': f'You are a professional translator to {target_language_name}.'},
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
        
        translation_line = None
        explanation_line = None
        confidence_line = None
        
        for line in content.split('\n'):
            if line.startswith('TRANSLATION:'):
                translation_line = line.replace('TRANSLATION:', '').strip()
            elif line.startswith('EXPLANATION:'):
                explanation_line = line.replace('EXPLANATION:', '').strip()
            elif line.startswith('CONFIDENCE:'):
                confidence_line = line.replace('CONFIDENCE:', '').strip()
        
        if not translation_line:
            paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
            if paragraphs:
                translation_line = paragraphs[0]
                if len(paragraphs) > 1:
                    explanation_line = paragraphs[1]
        
        return translation_line, explanation_line, confidence_line
        
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

def process_ts_file(ts_file, openai_url, openai_token, openai_model, debug=False, translate_empty=False):
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
        
        # Iterate through all contexts
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
            
            if debug:
                print(f"{Fore.CYAN}Debug - Processing context: {context_name}{Style.RESET_ALL}")
            
            # Iterate through all messages in the context
            for message in context.findall('message'):
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
                        if filename:
                            print(f"{Fore.BLUE}Location:{Style.RESET_ALL} {filename}:{line_no}")

                    print(f"{Fore.GREEN}Context:{Style.RESET_ALL} {context_name}")
                    print(f"{Fore.GREEN}Source:{Style.RESET_ALL} {source_text}")
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
                    
                    # Translate using OpenAI
                    if debug:
                        print(f"{Fore.CYAN}Translating...{Style.RESET_ALL}")

                    translated_text, explanation, confidence = translate_with_openai(
                        source_text, context_name, comment_text, extracomment_text,
                        target_language, openai_url, openai_token, openai_model, debug
                    )
                    
                    # If source text is missing (i.e. only "..." or "…"), move the error message to explanation and set confidence to 0.
                    if source_text.strip() in ["...", "…"]:
                        explanation = translated_text
                        translated_text = ""
                        confidence = "0%"
                    
                    if explanation:
                        print(f"{Fore.GREEN}Explanation:{Style.RESET_ALL} {explanation}")
                    if confidence:
                        print(f"{Fore.GREEN}Confidence:{Style.RESET_ALL} {confidence}")
                    if translated_text:
                        print(f"{Fore.GREEN}Translated text:{Style.RESET_ALL} {translated_text}")


                    # Ask for user confirmation
                    while True:
                        if not translated_text and explanation.startswith("I'm sorry, but it seems"):
                            prompt_str = f"{Fore.YELLOW}Accept this translation? (no/edit/quit): {Style.RESET_ALL}"
                            valid_choices = {'no', 'n', 'edit', 'e', 'quit', 'q'}
                        else:
                            prompt_str = f"{Fore.YELLOW}Accept this translation? (yes/no/edit/quit): {Style.RESET_ALL}"
                            valid_choices = {'yes', 'y', 'no', 'n', 'edit', 'quit', 'q'}
                        
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
        # Save the changes
        write_ts_file(tree, ts_file)
        print(f"\n{Fore.GREEN}Completed! Processed {processed_count} out of {unfinished_count + empty_count} total translations.{Style.RESET_ALL}")
        if translate_empty:
            print(f"{Fore.GREEN}Details: {unfinished_count} unfinished translations, {empty_count} empty translations.{Style.RESET_ALL}")
        
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
    
    # Process the TS file
    process_ts_file(args.ts_file, args.openai_url, args.openai_token, args.openai_model, args.debug, args.translate_empty)

if __name__ == "__main__":
    main()
