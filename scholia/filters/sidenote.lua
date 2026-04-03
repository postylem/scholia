-- sidenote.lua: Convert Pandoc footnotes to Tufte-style sidenotes.
-- Regular footnotes become numbered sidenotes.
-- Footnotes starting with {-} become unnumbered margin notes.
-- Uses checkbox toggle so sidenotes collapse inline on narrow screens.

local sidenote_count = 0

function Note(note)
  sidenote_count = sidenote_count + 1

  -- Check for margin note marker {-}
  local is_margin = false
  local blocks = note.content
  if #blocks > 0 then
    local first_block = blocks[1]
    if first_block.t == "Para" and #first_block.content > 0 then
      local first_inline = first_block.content[1]
      if first_inline.t == "Str" and first_inline.text:match("^{%-}") then
        is_margin = true
        if first_inline.text == "{-}" then
          table.remove(first_block.content, 1)
          if #first_block.content > 0 and first_block.content[1].t == "Space" then
            table.remove(first_block.content, 1)
          end
        else
          first_block.content[1].text = first_inline.text:sub(4)
        end
      end
    end
  end

  -- Render note content as HTML, preserving math for MathJax
  local html_content = pandoc.write(pandoc.Pandoc(blocks), "html", { html_math_method = "mathjax" })
  -- Unwrap single-paragraph notes
  html_content = html_content:gsub("^%s*<p>(.+)</p>%s*$", "%1")

  if is_margin then
    local id = "mn-" .. sidenote_count
    return pandoc.RawInline("html", string.format(
      '<label for="%s" class="margin-toggle">&#8853;</label>' ..
      '<input type="checkbox" id="%s" class="margin-toggle"/>' ..
      '<span class="marginnote">%s</span>',
      id, id, html_content
    ))
  else
    local id = "sn-" .. sidenote_count
    return pandoc.RawInline("html", string.format(
      '<label for="%s" class="margin-toggle sidenote-number">%d</label>' ..
      '<input type="checkbox" id="%s" class="margin-toggle"/>' ..
      '<span class="sidenote"><sup>%d</sup> %s</span>',
      id, sidenote_count, id, sidenote_count, html_content
    ))
  end
end
