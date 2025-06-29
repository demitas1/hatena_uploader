#!/usr/bin/env python3
"""
Markdown LaTeX Extractor
Extract LaTeX expressions from markdown files and render them as images.
"""

import argparse
import re
import os
import json
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib as mpl
from PIL import Image, ImageDraw
import numpy as np
from datetime import datetime


def extract_latex_expressions(markdown_content, convert_inline=False):
    """
    Extract LaTeX expressions from markdown content.
    Returns list of tuples: (expression, is_block, start_pos, end_pos, full_match)
    """
    expressions = []
    
    # Extract block equations ($$...$$)
    block_pattern = r'\$\$\s*(.*?)\s*\$\$'
    for match in re.finditer(block_pattern, markdown_content, re.DOTALL):
        expressions.append((
            match.group(1).strip(),  # expression
            True,                    # is_block
            match.start(),          # start_pos
            match.end(),            # end_pos
            match.group(0)          # full_match
        ))
    
    # Extract inline equations ($...$) only if convert_inline is True
    if convert_inline:
        inline_pattern = r'(?<!\$)\$(?!\$)(.*?)(?<!\$)\$(?!\$)'
        for match in re.finditer(inline_pattern, markdown_content):
            # Check if this match overlaps with any block equation
            overlaps = any(
                block_start <= match.start() < block_end or
                block_start < match.end() <= block_end
                for _, _, block_start, block_end, _ in expressions if block_start is not None
            )
            
            if not overlaps:
                expressions.append((
                    match.group(1).strip(),  # expression
                    False,                   # is_block
                    match.start(),          # start_pos
                    match.end(),            # end_pos
                    match.group(0)          # full_match
                ))
    
    # Sort by position to maintain order
    expressions.sort(key=lambda x: x[2])
    
    return expressions


def create_modified_markdown(markdown_content, expressions, image_mappings):
    """
    Create modified markdown with LaTeX expressions replaced by image links.
    """
    # Sort expressions by position in reverse order to avoid position shifts
    sorted_expressions = sorted(expressions, key=lambda x: x[2], reverse=True)
    
    modified_content = markdown_content
    
    for i, (expr, is_block, start_pos, end_pos, full_match) in enumerate(sorted_expressions):
        # Find the corresponding image mapping
        mapping = next((m for m in image_mappings if m['expression'] == expr), None)
        if mapping:
            # Create image link
            alt_text = expr[:50] + ('...' if len(expr) > 50 else '')
            image_link = f"![{alt_text}](./{mapping['filename']})"
            
            # Replace the LaTeX expression with image link
            modified_content = (
                modified_content[:start_pos] + 
                image_link + 
                modified_content[end_pos:]
            )
    
    return modified_content


def save_json_mapping(mappings, output_path):
    """
    Save the mapping data as JSON file.
    """
    json_data = {
        "mappings": mappings,
        "total_expressions": len(mappings),
        "generated_at": datetime.now().isoformat()
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)


def save_modified_markdown(content, output_path):
    """
    Save the modified markdown content.
    """
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)


def render_latex_to_image(latex_expr, output_path, color='black', bgcolor=None, format='png'):
    """
    Render LaTeX expression to image using matplotlib.
    """
    # Configure matplotlib for LaTeX rendering
    plt.rcParams['text.usetex'] = False  # Use mathtext instead of external LaTeX
    plt.rcParams['font.family'] = 'serif'
    plt.rcParams['mathtext.fontset'] = 'cm'
    
    # Create figure with transparent background
    fig, ax = plt.subplots(figsize=(10, 2))
    
    # Set background color
    if bgcolor is None:
        fig.patch.set_alpha(0)  # Transparent background
        ax.patch.set_alpha(0)
    else:
        fig.patch.set_facecolor(bgcolor)
        ax.patch.set_facecolor(bgcolor)
    
    # Remove axes
    ax.axis('off')
    
    try:
        # Render LaTeX expression
        ax.text(0.5, 0.5, f'${latex_expr}$', 
                horizontalalignment='center',
                verticalalignment='center',
                transform=ax.transAxes,
                fontsize=16,
                color=color)
        
        # Save with tight layout
        plt.tight_layout()
        
        if format.lower() == 'jpg' or format.lower() == 'jpeg':
            # For JPEG, we need to handle transparency
            if bgcolor is None:
                # Set white background for JPEG
                fig.patch.set_facecolor('white')
                ax.patch.set_facecolor('white')
            plt.savefig(output_path, format='jpeg', bbox_inches='tight', 
                       pad_inches=0.1, dpi=300, facecolor=fig.get_facecolor())
        else:
            # PNG supports transparency
            plt.savefig(output_path, format='png', bbox_inches='tight', 
                       pad_inches=0.1, dpi=300, transparent=(bgcolor is None))
        
        plt.close(fig)
        return True
        
    except Exception as e:
        print(f"Error rendering LaTeX '{latex_expr}': {e}")
        plt.close(fig)
        return False


def main():
    parser = argparse.ArgumentParser(description='Extract LaTeX from markdown and render as images')
    parser.add_argument('input_file', help='Input markdown file')
    parser.add_argument('--format', choices=['png', 'jpg', 'jpeg'], default='png',
                        help='Output image format (default: png)')
    parser.add_argument('--color', default='black',
                        help='Text color (default: black)')
    parser.add_argument('--bgcolor', default=None,
                        help='Background color (default: transparent)')
    parser.add_argument('--output-dir', default='.',
                        help='Output directory (default: current directory)')
    parser.add_argument('--convert-inline', action='store_true',
                        help='Convert inline LaTeX expressions (default: only block expressions)')
    
    args = parser.parse_args()
    
    # Check if input file exists
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"Error: Input file '{args.input_file}' not found")
        return 1
    
    # Create output directory if it doesn't exist
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Read markdown file
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
    except Exception as e:
        print(f"Error reading file: {e}")
        return 1
    
    # Extract LaTeX expressions
    expressions = extract_latex_expressions(markdown_content, args.convert_inline)
    
    if not expressions:
        expression_type = "LaTeX expressions" if args.convert_inline else "block LaTeX expressions"
        print(f"No {expression_type} found in the markdown file")
        if not args.convert_inline:
            print("Tip: Use --convert-inline to also convert inline expressions ($...$)")
        return 0
    
    expression_type = "LaTeX expressions" if args.convert_inline else "block LaTeX expressions"
    print(f"Found {len(expressions)} {expression_type}")
    
    # Prepare for image mappings
    image_mappings = []
    
    # Render each expression
    successful_renders = 0
    for i, (expr, is_block, start_pos, end_pos, full_match) in enumerate(expressions, 1):
        # Determine file extension
        ext = 'jpg' if args.format.lower() in ['jpg', 'jpeg'] else 'png'
        filename = f"image-latex{i}.{ext}"
        output_path = output_dir / filename
        
        expr_type = "block" if is_block else "inline"
        print(f"Rendering {expr_type} expression {i}: {expr[:50]}{'...' if len(expr) > 50 else ''}")
        
        if render_latex_to_image(expr, output_path, args.color, args.bgcolor, args.format):
            print(f"  → Saved as {output_path}")
            successful_renders += 1
            
            # Add to mappings
            image_mappings.append({
                "id": f"latex{i}",
                "expression": expr,
                "filename": filename,
                "is_block": is_block,
                "original_match": full_match
            })
        else:
            print(f"  → Failed to render")
    
    if successful_renders > 0:
        # Create modified markdown
        modified_markdown = create_modified_markdown(markdown_content, expressions, image_mappings)
        
        # Save modified markdown
        input_stem = input_path.stem
        modified_markdown_path = output_dir / f"{input_stem}_modified.md"
        save_modified_markdown(modified_markdown, modified_markdown_path)
        print(f"Modified markdown saved as: {modified_markdown_path}")
        
        # Save JSON mapping
        json_filename = f"{input_stem}.json"
        json_path = output_dir / json_filename
        save_json_mapping(image_mappings, json_path)
        print(f"JSON mapping saved as: {json_path}")
    
    print(f"\nCompleted: {successful_renders}/{len(expressions)} images rendered successfully")
    return 0


if __name__ == '__main__':
    exit(main())
