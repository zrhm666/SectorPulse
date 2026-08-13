import typer
app=typer.Typer(no_args_is_help=True)
@app.command("phase0-probe")
def phase0_probe():
    typer.echo("Phase 0 probe scaffold is ready; live provider execution is pending.")
