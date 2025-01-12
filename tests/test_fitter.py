'''
Module containing tests for Fitter class
'''
# pylint: disable=import-error

import os
from dataclasses import dataclass

import numpy
import ROOT
import pytest
import zfit
from ROOT                    import RDataFrame, RDF
from zfit.core.basepdf       import BasePDF

from dmu.plotting.plotter_1d import Plotter1D as Plotter
from dmu.logging.log_store   import LogStore

from rx_calibration.hltcalibration.fitter import Fitter

log = LogStore.add_logger('rx_calibration:test_fitter')
# --------------------------------------------
@dataclass
class Data:
    '''
    Class holding shared attributes
    '''
    out_dir    = '/tmp/rx_calibration/tests/fitter'
    mass_name  = 'mass'
    d_nentries = {
            'signal'     :   5_000,
            'background' : 500_000}

    obs        = zfit.Space(mass_name, limits=(4800, 6000))
# --------------------------------------------
@pytest.fixture(scope='session', autouse=True)
def _initialize():
    LogStore.set_level('rx_calibration:fitter', 10)
# --------------------------------------------
def _concatenate_rdf(rdf_1 : RDataFrame, rdf_2 : RDataFrame) -> RDataFrame:
    arr_val1 = rdf_1.AsNumpy([Data.mass_name])[Data.mass_name]
    arr_val2 = rdf_2.AsNumpy([Data.mass_name])[Data.mass_name]

    arr_val  = numpy.concatenate([arr_val1, arr_val2])

    return RDF.FromNumpy({Data.mass_name : arr_val})
# --------------------------------------------
def _get_rdf(kind : str) -> RDataFrame:
    out_path = f'{Data.out_dir}/{kind}.root'
    if os.path.isfile(out_path):
        log.warning(f'Reloading: {out_path}')
        rdf = RDataFrame('tree', out_path)
        return rdf

    if kind == 'data':
        rdf_s = _get_rdf(    'signal')
        rdf_b = _get_rdf('background')
        rdf   = _concatenate_rdf(rdf_s, rdf_b)
        return rdf

    nentries = Data.d_nentries[kind]
    rdf      = RDataFrame(nentries)

    if kind == 'background':
        rdf = rdf.Define(Data.mass_name, 'TRandom3 r(0); return r.Exp(1000.);')

    if kind == 'signal':
        rdf = rdf.Define(Data.mass_name, 'TRandom3 r(0); return r.Gaus(5300, 50);')

    rdf = rdf.Filter(f'{Data.mass_name} > 4600')

    rdf.Snapshot('tree', out_path)

    return rdf
# --------------------------------------------
def _plot_rdf(d_rdf : dict[RDataFrame, RDataFrame]) -> None:
    cfg = {}
    cfg['saving'] = {'plt_dir' : '/tmp/rx_calibration/tests/fitter'}
    cfg['plots' ] = {Data.mass_name : {}}
    cfg['plots' ][Data.mass_name]['binning'] = [4500, 6000, 40]
    cfg['plots' ][Data.mass_name]['name'   ] = 'mass'

    ptr=Plotter(d_rdf=d_rdf, cfg=cfg)
    ptr.run()
# --------------------------------------------
def _get_pdf(kind : str) -> BasePDF:
    if   kind == 'signal':
        mu  = zfit.Parameter("mu_flt", 5300, 5200, 5400)
        sg  = zfit.Parameter(    "sg",  10,    10,  100)
        pdf = zfit.pdf.Gauss(obs=Data.obs, mu=mu, sigma=sg)
    elif kind == 'background':
        lam = zfit.param.Parameter('lam' ,   -1/1000.,  -10/1000.,  0)
        pdf = zfit.pdf.Exponential(lam = lam, obs = Data.obs)
    else:
        raise ValueError(f'Invalid kind: {kind}')

    return pdf
# --------------------------------------------
def _get_conf() -> dict:
    return {
            'plot_nbins'     : 50,
            'error_method'   : 'minuit_hesse',
            'weights_column' : 'weights'
            }
# --------------------------------------------
def test_simple():
    '''
    Simplest test of Fitter class
    '''
    rdf_sim = _get_rdf(kind = 'signal')
    rdf_dat = _get_rdf(kind =   'data')

    #_plot_rdf({'MC' : rdf_sim, 'Data' : rdf_dat})

    pdf_s   = _get_pdf(kind =     'signal')
    pdf_b   = _get_pdf(kind = 'background')
    conf    = _get_conf()

    obj = Fitter(
            data=rdf_dat,
            sim =rdf_sim,
            smod=pdf_s,
            bmod=pdf_b,
            conf=conf,
            )

    _ = obj.fit()
# --------------------------------------------
