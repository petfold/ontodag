# Build the OntoDAG/FCA tutorial paper.
#
#   make            -- experiments, figures, then the PDF
#   make figures    -- regenerate the dot2tex fragments only
#   make experiments-- rerun the measurements the paper quotes
#   make clean      -- remove build litter (keeps the PDF)
#
# Needs: pdflatex, bibtex, graphviz (dot), dot2tex, python3.

DOC      := ontodag-fca
DOTS     := $(wildcard figures/*.dot)
DOTTEX   := $(DOTS:.dot=.tex)

# dot2tex emits a bare TikZ body (no picture environment), which the paper
# wraps itself so it can set its own scale and styles per figure.
DOT2TEX  := dot2tex --format tikz --codeonly --texmode raw --usepdflatex

.PHONY: all figures experiments clean distclean

all: $(DOC).pdf

experiments:
	python3 experiments/fca_experiments.py

figures: $(DOTTEX)

figures/%.tex: figures/%.dot
	$(DOT2TEX) -o $@ $<

$(DOC).pdf: $(DOC).tex $(DOC).bib $(DOTTEX) $(wildcard sections/*.tex)
	pdflatex -interaction=nonstopmode $(DOC).tex >/dev/null
	-bibtex $(DOC) >/dev/null
	pdflatex -interaction=nonstopmode $(DOC).tex >/dev/null
	pdflatex -interaction=nonstopmode $(DOC).tex >/dev/null
	@# a fourth pass: the figures move enough on pass three that
	@# cross-references only settle here
	pdflatex -interaction=nonstopmode $(DOC).tex | tail -5
	@echo "--- $(DOC).pdf: $$(pdfinfo $(DOC).pdf 2>/dev/null | grep Pages || echo '?') ---"

clean:
	rm -f $(DOC).aux $(DOC).log $(DOC).out $(DOC).toc $(DOC).bbl \
	      $(DOC).blg $(DOC).lof $(DOC).lot $(DOC).nav $(DOC).snm

distclean: clean
	rm -f $(DOC).pdf $(DOTTEX)
