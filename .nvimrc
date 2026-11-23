" Persistently track file undo, next to each file as .<name>.un~
set undofile
set undodir=.
" Record every story edit with replayvim, for words_written.py. The plugin
" is loaded by init.vim before this file runs, so g:replayvim's auto_attach
" would come too late; start tracking each story as it's opened instead.
" Silent, or its message plus the file info makes a hit-enter prompt.
augroup TravelBookReplay
  autocmd!
  autocmd BufReadPost,BufNewFile */raw/stories/*.md silent ReplayVimStartTracking
augroup END
