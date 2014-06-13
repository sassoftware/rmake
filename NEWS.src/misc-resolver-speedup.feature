The resolver will now pre-cache dependency information from resolveTroves. This
uses more RAM but speeds up large resolve jobs by as much as 2x. Conary 2.5.4
is required in order to take advantage of the speedup.
