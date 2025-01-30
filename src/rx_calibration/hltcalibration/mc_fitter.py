'''
Module holding FitComponent class
'''

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
from dmu.stats.minimizers   import AnealingMinimizer

from rx_calibration.hltcalibration.parameter import Parameter

log   = LogStore.add_logger('rx_calibration:mc_fitter')
# ----------------------------------------
class MCFitter:
    '''
    Class meant to represent a fitting component

    It will take the PDF and optionally a ROOT dataframe modelling the corresponding component in MC.
    If the dataframe is passed, it will fit the PDF and fix the parameters whose names do not end with
    `_flt`. It can also plot the fit. The configuration looks like:

    ```yaml
    name    : signal
    out_dir : /tmp/rx_calibration/tests/fit_component
    fitting :
        error_method   : minuit_hesse
        weights_column : weights
    plotting:
        nbins   : 50
        stacked : true
    ```
    '''
    # --------------------
    def __init__(self, cfg : dict, rdf : Union[RDataFrame,None], pdf : BasePDF):
        self._name      = cfg['name']
        self._fit_cfg   = cfg['fitting' ] if 'fitting'  in cfg else None
        self._plt_cfg   = cfg['plotting'] if 'plotting' in cfg else None
        self._out_dir   : str

        if self._fit_cfg is not None:
            self._out_dir = cfg['out_dir']

        self._rdf       = rdf
        self._pdf       = pdf
        self._obs       = self._pdf.space
        self._obs_name, = self._pdf.obs
        self._minimizer = AnealingMinimizer(ntries=10, pvalue=0.05)
    # --------------------
    @property
    def name(self) -> str:
        '''
        Returns the name of the fit component
        '''
        return self._name
    # --------------------
    @property
    def pdf(self) -> BasePDF:
        return self._pdf
    # --------------------
    def _add_weights(self, rdf : RDataFrame, wgt_name : str) -> RDataFrame:
        v_col  = rdf.GetColumnNames()
        l_col  = [col.c_str() for col in v_col]

        if wgt_name in l_col:
            log.debug(f'Weights column {wgt_name} found, not defining ones')
            return rdf

        log.debug(f'Weights column {wgt_name} not found, defining \"weights\" as ones')
        rdf = rdf.Define(wgt_name, '1.0')

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

        os.makedirs(self._out_dir, exist_ok=True)

        obj=ZFitPlotter(data=data, model=model)
        obj.plot(**self._plt_cfg)

        plot_path = f'{self._out_dir}/{self._name}.png'
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
            par.floating = False

            log.info(f'{name:<20}{"-->":<20}{val:<20.3f}')
    # --------------------
    def run(self) -> Parameter:
        '''
        Will return the PDF
        '''
        if self._fit_cfg is None:
            return self._pdf

        if self._rdf is None:
            raise ValueError('Dataframe not found')

        pars_path= f'{self._out_dir}/{self._name}.json'
        if not os.path.isfile(pars_path):
            data=self._get_data()
            par = self._fit(data)
            self._plot_fit(data, self._pdf)
            par.to_json(pars_path)
        else:
            log.warning(f'Fit parameters for component {self._name} found, loading: {pars_path}')
            par = Parameter.from_json(pars_path)

        self._fix_tails(par)

        return par
# ----------------------------------------
