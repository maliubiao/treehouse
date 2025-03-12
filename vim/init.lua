--  ~/.config/nvim/init.lua, 用Packer当包管理，先安装Packer，然后打开nvim :PackerSync, 安装插件

vim.cmd [[packadd packer.nvim]]

return require('packer').startup(function(use)
  -- Packer can manage itself
  use 'wbthomason/packer.nvim'
  use "williamboman/mason.nvim"
  use 'rstacruz/vim-closer'
  use 'ellisonleao/gruvbox.nvim'
  use 'neovim/nvim-lspconfig'
  use 'williamboman/mason-lspconfig.nvim'
  use {
    'nvim-treesitter/nvim-treesitter',
    run = ':TSUpdate'
  }
  -- UI plugins
  use {
    'rcarriga/nvim-notify',
    config = function()
      vim.notify = require('notify')
    end
  }
  use 'stevearc/dressing.nvim'
  use {
    'akinsho/bufferline.nvim',
    tag = "v3.*",
    requires = 'nvim-tree/nvim-web-devicons'
  }
  use {
    'nvim-lualine/lualine.nvim',
    requires = { 'nvim-tree/nvim-web-devicons', opt = true }
  }
  use 'lukas-reineke/indent-blankline.nvim'
  use {
    'echasnovski/mini.indentscope',
    branch = 'stable'
  }
  use {
    'folke/noice.nvim',
    requires = {
      'MunifTanjim/nui.nvim',
      'rcarriga/nvim-notify',
    }
  }
  use {
    'goolord/alpha-nvim',
    requires = { 'nvim-tree/nvim-web-devicons' }
  }
  use 'SmiteshP/nvim-navic'
  use 'nvim-tree/nvim-web-devicons'
  use 'MunifTanjim/nui.nvim'

  -- Coding plugins
  use {
    'L3MON4D3/LuaSnip',
    build = (not jit.os:find("Windows")) and "make install_jsregexp" or nil,
    requires = { 'rafamadriz/friendly-snippets' },
    config = function()
      require("luasnip.loaders.from_vscode").lazy_load()
    end
  }
  use {
    'hrsh7th/nvim-cmp',
    requires = {
      'hrsh7th/cmp-nvim-lsp',
      'hrsh7th/cmp-buffer',
      'hrsh7th/cmp-path',
      'saadparwaiz1/cmp_luasnip',
    }
  }
  use 'echasnovski/mini.pairs'
  use {
    'echasnovski/mini.surround',
    config = function()
      require('mini.surround').setup({
        mappings = {
          add = 'gsa',  -- Changed from gza
          delete = 'gsd',  -- Changed from gzd
          find = 'gsf',  -- Changed from gzf
          find_left = 'gsF',  -- Changed from gzF
          highlight = 'gsh',  -- Changed from gzh
          replace = 'gsr',  -- Changed from gzr
          update_n_lines = 'gsn',  -- Changed from gzn
        }
      })
    end
  }
  use 'JoosepAlviste/nvim-ts-context-commentstring'
  use {
    'echasnovski/mini.comment',
    config = function()
      require('mini.comment').setup({
        hooks = {
          pre = function()
            require('ts_context_commentstring.internal').update_commentstring({})
          end,
        },
      })
    end
  }
  use {
    'echasnovski/mini.ai',
    config = function()
      local ai = require('mini.ai')
      require('mini.ai').setup({
        n_lines = 500,
        custom_textobjects = {
          o = ai.gen_spec.treesitter({
            a = { '@block.outer', '@conditional.outer', '@loop.outer' },
            i = { '@block.inner', '@conditional.inner', '@loop.inner' },
          }, {}),
          f = ai.gen_spec.treesitter({ a = '@function.outer', i = '@function.inner' }, {}),
          c = ai.gen_spec.treesitter({ a = '@class.outer', i = '@class.inner' }, {}),
        }
      })
    end
  }

  -- Newly added plugins
  use {
    'nvim-neo-tree/neo-tree.nvim',
    branch = 'v3.x',
    requires = {
      'nvim-lua/plenary.nvim',
      'nvim-tree/nvim-web-devicons',
      'MunifTanjim/nui.nvim',
    }
  }
  use {
    'nvim-telescope/telescope.nvim',
    tag = '0.1.5',
    requires = { 'nvim-lua/plenary.nvim' }
  }
  use {
    'folke/which-key.nvim',
    config = function()
      require('which-key').setup {
        plugins = {
          spelling = { enabled = true },
          presets = { operators = false }
        },
        win = {  -- Changed from window
          border = "single",
          padding = { 1, 2, 1, 2 }
        }
      }
    end
  }
  use {
    'lewis6991/gitsigns.nvim',
    config = function()
      require('gitsigns').setup()
    end
  }
  use 'RRethy/vim-illuminate'
  use 'echasnovski/mini.bufremove'
  use {
    'folke/trouble.nvim',
    requires = 'nvim-tree/nvim-web-devicons',
    config = function()
      require('trouble').setup()
    end
  }
  use 'folke/todo-comments.nvim'

  require("gruvbox").setup({
    undercurl = true,
    underline = true,
    bold = true,
    italic = {
      strings = false,
      emphasis = false,
      comments = false,
      operators = false,
      folds = true,
    },
    strikethrough = true,
    invert_selection = false,
    invert_signs = false,
    invert_tabline = false,
    invert_intend_guides = false,
    inverse = true,
    dim_inactive = false,
    transparent_mode = false,
  })
  vim.o.background = 'light'
  vim.cmd("colorscheme gruvbox")

  -- Treesitter configuration
  require('nvim-treesitter.configs').setup({
    ensure_installed = { 
      'python', 'go', 'c', 'lua', 'vim',
      'javascript', 'typescript', 'tsx', 'json', 'yaml', 'toml',
      'java', 'rust', 'bash', 'markdown', 'css', 'html', 'dockerfile'
    },
    sync_install = false,
    auto_install = true,
    highlight = {
      enable = true,
      additional_vim_regex_highlighting = false,
    },
  })

  -- LSP configuration
  require("mason").setup()
  require("mason-lspconfig").setup({})

  local lspconfig = require('lspconfig')
  lspconfig.pyright.setup{}
  lspconfig.gopls.setup{}
  lspconfig.clangd.setup{}

  -- UI configurations
  require('bufferline').setup{
    options = {
      diagnostics = {
        sources = {"nvim_lsp"},
        severity_sort = true,
      },
      always_show_bufferline = false,
      offsets = {
        {
          filetype = "neo-tree",
          text = "Neo-tree",
          highlight = "Directory",
          text_align = "left",
        },
      },
    }
  }

  require('lualine').setup{
    options = {
      theme = 'gruvbox',
      component_separators = { left = '|', right = '|'},
      section_separators = { left = '', right = ''},
    },
    sections = {
      lualine_a = {'mode'},
      lualine_b = {'branch', 'diff'},
      lualine_c = {'filename'},
      lualine_x = {'encoding', 'fileformat', 'filetype'},
      lualine_y = {'progress'},
      lualine_z = {'location'}
    }
  }

  require("ibl").setup { indent = { highlight = highlight } }

  require('mini.indentscope').setup{
    symbol = '│',
    options = { try_as_border = true },
  }

  require('noice').setup{
    lsp = {
      override = {
        ['vim.lsp.util.convert_input_to_markdown_lines'] = true,
        ['vim.lsp.util.stylize_markdown'] = true,
      },
    },
    presets = {
      bottom_search = true,
      command_palette = true,
      long_message_to_split = true,
    },
  }

  -- nvim-cmp configuration
  local cmp = require('cmp')
  cmp.setup({
    completion = {
      completeopt = 'menu,menuone,noinsert',
    },
    snippet = {
      expand = function(args)
        require('luasnip').lsp_expand(args.body)
      end,
    },
    mapping = cmp.mapping.preset.insert({
      ['<C-n>'] = cmp.mapping.select_next_item({ behavior = cmp.SelectBehavior.Insert }),
      ['<C-p>'] = cmp.mapping.select_prev_item({ behavior = cmp.SelectBehavior.Insert }),
      ['<C-b>'] = cmp.mapping.scroll_docs(-4),
      ['<C-f>'] = cmp.mapping.scroll_docs(4),
      ['<C-Space>'] = cmp.mapping.complete(),
      ['<C-e>'] = cmp.mapping.abort(),
      ['<CR>'] = cmp.mapping.confirm({ select = true }),
      ['<S-CR>'] = cmp.mapping.confirm({
        behavior = cmp.ConfirmBehavior.Replace,
        select = true,
      }),
    }),
    sources = cmp.config.sources({
      { name = 'nvim_lsp' },
      { name = 'luasnip' },
      { name = 'buffer' },
      { name = 'path' },
    }),
    formatting = {
      format = function(_, item)
        local icons = {
          Text = ' ',
          Method = ' ',
          Function = ' ',
          Constructor = ' ',
          Field = ' ',
          Variable = ' ',
          Class = ' ',
          Interface = ' ',
          Module = ' ',
          Property = ' ',
          Unit = ' ',
          Value = ' ',
          Enum = ' ',
          Keyword = ' ',
          Snippet = ' ',
          Color = ' ',
          File = ' ',
          Reference = ' ',
          Folder = ' ',
          EnumMember = ' ',
          Constant = ' ',
          Struct = ' ',
          Event = ' ',
          Operator = ' ',
          TypeParameter = ' ',
        }
        item.kind = (icons[item.kind] or '') .. item.kind
        return item
      end,
    },
    experimental = {
      ghost_text = {
        hl_group = 'LspCodeLens',
      },
    },
  })

  -- New plugin configurations
  require('which-key').setup {
    plugins = {
      spelling = { enabled = true },
      presets = { operators = false }
    },
    win = {  -- Changed from window
      border = "single",
      padding = { 1, 2, 1, 2 }
    }
  }

  require('gitsigns').setup {
    signs = {
      add = { text = '▎' },
      change = { text = '▎' },
      delete = { text = '' },
      topdelete = { text = '' },
      changedelete = { text = '▎' },
    },
    on_attach = function(bufnr)
      local gs = package.loaded.gitsigns
      local map = function(mode, l, r, opts)
        opts = opts or {}
        opts.buffer = bufnr
        vim.keymap.set(mode, l, r, opts)
      end

      map('n', ']h', gs.next_hunk, { desc = 'Next Hunk' })
      map('n', '[h', gs.prev_hunk, { desc = 'Prev Hunk' })
      map('n', '<leader>ghp', gs.preview_hunk, { desc = 'Preview Hunk' })
    end
  }

  require('telescope').setup {
    defaults = {
      mappings = {
        i = {
          ['<C-u>'] = false,
          ['<C-d>'] = false,
        },
      },
    },
  }

  require('neo-tree').setup {
    close_if_last_window = true,
    filesystem = {
      follow_current_file = {
        enabled = true
      },
      hijack_netrw_behavior = "open_current",
    }
  }

  require('trouble').setup {
    auto_open = false,
    auto_close = true,
    use_diagnostic_signs = true
  }

  require('todo-comments').setup {
    signs = false,
    keywords = {
      FIX = { color = "error" },
      TODO = { color = "hint" },
    }
  }

  require('alpha').setup(require('alpha.themes.dashboard').config)
  require('nvim-navic').setup{
    separator = ' ',
    highlight = true,
  }
end)
