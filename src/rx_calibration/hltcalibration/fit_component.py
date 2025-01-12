'''
Module holding FitComponent class
'''
# pylint: disable=import-error, unused-import, too-many-positional-arguments, too-many-arguments

import os
from typing                 import Union

import ROOT
import zfit
import matplotlib.pyplot as plt

from ROOT                   import RDataFrame
from zfit.core.data         import Data      as zdata
from zfit.core.basepdf      import BasePDF
from dmu.logging.log_store  import LogStore
from dmu.stats.utilities    import print_pdf
from dmu.stats.zfit_plotter import ZFitPlotter

from rx_calibration.hltcalibration.parameter import Parameter

log   = LogStore.add_logger('rx_calibration:fit_component')
# ----------------------------------------
class FitComponent:
    '''
    Class meant to represent a fitting component
    '''
    # --------------------
    def __init__(self, cfg : dict, rdf : Union[RDataFrame,None], pdf : BasePDF):
        self._name      = cfg['name']
        self._fit_cfg   = cfg['fitting' ] if 'fitting'  in cfg else None
        self._plt_cfg   = cfg['plotting'] if 'plotting' in cfg else None

        self._rdf       = rdf
        self._pdf       = pdf
        self._obs       = self._pdf.space
        self._obs_name, = self._pdf.obs
        self._minimizer = zfit.minimize.Minuit()
    # --------------------
    def _add_weights(self, rdf : RDataFrame, wgt_name : str) -> RDataFrame:
        v_col  = rdf.GetColumnNames()
        l_col  = [col.c_str() for col in v_col]

        if wgt_name in l_col:
            log.debug(f'Weights column {wgt_name} found, not defining ones')
            return rdf

        log.debug(f'Weights column {wgt_name} not found, defining \"weights\" as ones')
        rdf = rdf.Define(wgt_name, '1')

        return rdf
    # --------------------
    def _fit(self, zdt : zdata) -> Parameter:
        log.info(f'Fitting component {self._name}')

        print_pdf(self._pdf)

        nll = zfit.loss.UnbinnedNLL(model=self._pdf, data=zdt)
        res = self._minimizer.minimize(nll)

        print(res)
        par = self._res_to_par(res)

        return par
    # -------------------------------
    def _res_to_par(self, res : zfit.result.FitResult) -> Parameter:
        if self._fit_cfg is None:
            raise ValueError('Cannot find fit configuration')

        err_method = self._fit_cfg['error_method']

        if err_method != 'minuit_hesse':
            raise NotImplementedError(f'Method {err_method} not implemented, only minuit_hesse allowed')

        res.hesse(method=err_method)
        res.freeze()
        obj = Parameter()
        for par_name, d_val in res.params.items():
            val : float = d_val['value']
            err : float = d_val['hesse']['error']

            obj[par_name] = val, err

        return obj
    # -------------------------------
    def _get_data(self) -> zdata:
        if self._fit_cfg is None:
            raise ValueError('Cannot find fit configuration')

        weights_column = self._fit_cfg['weights_column']
        rdf            = self._add_weights(self._rdf, weights_column)
        d_data         = rdf.AsNumpy([self._obs_name, weights_column])

        arr_obs = d_data[self._obs_name]
        arr_wgt = d_data[weights_column]
        data    = zfit.Data.from_numpy(self._obs, array=arr_obs, weights=arr_wgt)

        return data
    # --------------------
    def _plot_fit(self, data : zdata, model : BasePDF):
        if self._plt_cfg is None:
            log.warning('No plotting configuration found, will skip plotting')
            return

        plot_dir = self._plt_cfg['plot_dir']
        del self._plt_cfg['plot_dir']

        os.makedirs(plot_dir, exist_ok=True)

        obj=ZFitPlotter(data=data, model=model)
        obj.plot(**self._plt_cfg)

        plot_path = f'{plot_dir}/{self._name}.png'
        log.info(f'Saving fit plot to: {plot_path}')
        plt.savefig(plot_path)
    # -------------------------------
    def _fix_tails(self, sig_par : Parameter) -> None:
        s_par = self._pdf.get_params()

        log.info(60 * '-')
        log.info('Fixing tails')
        log.info(60 * '-')
        for par in s_par:
            name = par.name
            if name not in sig_par:
                log.debug(f'Skipping non signal parameter: {name}')
                continue

            if name.endswith('_flt'):
                log.debug(f'Not fixing {name}')
                continue

            val, _ = sig_par[name]

            par.set_value(val)
            par.floating = True

            log.info(f'{name:<20}{"-->":<20}{val:<20.3f}')
    # --------------------
    def get_pdf(self) -> BasePDF:
        '''
        Will return the PDF
        '''
        if self._fit_cfg is None:
            return self._pdf

        if self._rdf is None:
            raise ValueError('Dataframe not found')

        data=self._get_data()

        par = self._fit(data)
        self._fix_tails(par)
        self._plot_fit(data, self._pdf)

        return self._pdf
# ----------------------------------------
