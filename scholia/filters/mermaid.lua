-- mermaid.lua: Render mermaid diagrams in Pandoc output.
-- HTML: emit <pre class="mermaid"> for client-side mermaid.js rendering.
-- Other formats (PDF, LaTeX): render to PNG via mmdc (mermaid-cli),
-- falling back to a plain code block if mmdc is not installed.

local counter = 0
local mmdc_checked = false
local mmdc_available = false

local function check_mmdc()
  if mmdc_checked then return mmdc_available end
  mmdc_checked = true
  local handle = io.popen("mmdc --version 2>/dev/null")
  if handle then
    local result = handle:read("*a")
    handle:close()
    mmdc_available = (result ~= nil and result ~= "")
  end
  if not mmdc_available then
    io.stderr:write(
      "WARNING: mermaid-cli (mmdc) not found; mermaid diagrams will render as code blocks.\n" ..
      "  Install with: npm install -g @mermaid-js/mermaid-cli\n"
    )
  end
  return mmdc_available
end

function CodeBlock(block)
  if block.classes[1] ~= "mermaid" then return nil end

  -- HTML: client-side rendering via mermaid.js
  if FORMAT:match("html") then
    local escaped = block.text
      :gsub("&", "&amp;")
      :gsub("<", "&lt;")
      :gsub(">", "&gt;")
      :gsub('"', "&quot;")
    return pandoc.RawBlock("html",
      '<pre class="mermaid">\n' .. escaped .. '\n</pre>')
  end

  -- Non-HTML: render via mmdc, or keep as code block
  if not check_mmdc() then
    return nil
  end

  counter = counter + 1
  local input_path = os.tmpname()
  local output_path = os.tmpname() .. ".png"

  local f = io.open(input_path, "w")
  if not f then return nil end
  f:write(block.text)
  f:close()

  local ok = os.execute(string.format(
    'mmdc -i "%s" -o "%s" -b transparent 2>/dev/null',
    input_path, output_path))

  os.remove(input_path)

  if not ok then
    io.stderr:write("WARNING: mmdc failed to render a mermaid diagram\n")
    return nil
  end

  return pandoc.Para({pandoc.Image({}, output_path)})
end
