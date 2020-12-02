from numpy import *
from scipy.integrate import *
from scipy.interpolate import *
from scipy.optimize import curve_fit
from scipy.signal import savgol_filter
import os

import hdfoutput as hdf
import geometry as geo
import bassun as bs
import beta as beta

import configparser as cp
conffile = 'globals.conf'
config = cp.ConfigParser(inline_comment_prefixes="#")
config.read(conffile)

ifplot =  config['DEFAULT'].getboolean('ifplot')

if ifplot:
    import plots
    from matplotlib.pyplot import ioff
    ioff()

def readtireout(infile, ncol = 0):
    '''
    reading a tireout ASCII file
    ncol = 1 for rho
    ncol = 2 for v
    ncol = 3 for U/Umag
    '''
    lines = loadtxt(infile+'.dat', comments="#")
    r = squeeze(lines[:,0])
    if size(ncol) <= 1:
        q = squeeze(lines[:,ncol])
    else:
        q = []
        for k in arange(size(ncol)):
            q.append(squeeze(lines[:,ncol[k]]))
    return r, q

def galjaread(infile):
    '''
    reads the results of BS-type stationary solution and outputs x = R/RNS and
    u=u/umag
    '''
    lines = loadtxt(infile+'.dat', comments="#", delimiter="\t", unpack=False)
    
    x = squeeze(lines[:,0]) ; u = 3.*squeeze(lines[:,2]) ; v = squeeze(lines[:,3])
    prat =  squeeze(lines[:,6])

    #    plots.someplots(x, [v], name=infile+'_u', ylog=True, formatsequence=['k-'])
    
    return x, u, v, prat

def comparer(ingalja, inpasha, nentry = 1000, ifhdf = False, vnorm = None, conf = 'DEFAULT', vone = None):

    xg, ug, vg, pratg = galjaread(ingalja)
    if vone is not None:
        vg *= vone
    
    rstar = config[conf].getfloat('rstar')
    m1 = config[conf].getfloat('m1')
    mu30 = config[conf].getfloat('mu30')
    mdot = config[conf].getfloat('mdot') * 4.*pi
    afac = config[conf].getfloat('afac')
    mass1 = config[conf].getfloat('m1')
    realxirad = config[conf].getfloat('xirad')
    mow = config[conf].getfloat('mow')
    b12 = 2.*mu30*(rstar*m1/6.8)**(-3) # dipolar magnetic field on the pole, 1e12Gs units
    umag = b12**2*2.29e6*m1
    betacoeff = config[conf].getfloat('betacoeff') * (m1)**(-0.25)/mow

    if vnorm is not None:
        vg *= vnorm 

    if ifhdf:
        entry, t, l, xp, sth, rho, up, vp, qloss, glo  = read(inhdf, nentry)
    else:
        xp, qp = readtireout(inpasha, ncol = [3, 2, 1])
        up, vp, rhop = qp
    geofile = os.path.dirname(inpasha)+"/geo.dat"
    r, theta, alpha, across, l, delta = geo.gread(geofile)
   
    umagtar = umag * (1.+3.*cos(theta)**2)/4. * xp**(-6.)
    
    betap = beta.Fbeta(rhop, up * umagtar, betacoeff)
    pratp = betap / (1.-betap)

    # internal temperatures:
    tempp = (up * umagtar / mass1)**(0.25) * 3.35523 # keV
    umagtar_g = umag * (1.+3.*(1.-xg/xp.max()))/4. * xg**(-6.)
    tempg = (ug * umagtar_g / mass1)**(0.25) * 3.35523 # keV
    
    if ifplot:
        outdir = os.path.dirname(ingalja)+'/'
        plots.someplots([xg, xp], [ug, up], name=outdir+'BScompare_u', ylog=True, formatsequence=['k-', 'r--'], xtitle = r'$R/R_{\rm NS}$', ytitle =  r'$U/U_{\rm mag}$', multix = True)
        plots.someplots([xp, xg, xp, xp], [-vp, -vg, 1./sqrt(rstar*xp), 1./sqrt(rstar*xp)/7.], name=outdir+'BScompare_v', ylog=True, formatsequence=['r--', 'k-', 'b:', 'b:'], xtitle = r'$R/R_{\rm NS}$', ytitle =  r'$-v/c$', multix = True)
        plots.someplots([xg, xp], [pratg, pratp], name=outdir+'BScompare_p', ylog=False, formatsequence=['k-', 'r--'], xtitle = r'$R/R_{\rm NS}$', ytitle =  r'$P_{\rm gas} / P_{\rm rad}$', multix = True)
        plots.someplots([xg, xp], [tempg, tempp], name=outdir+'BScompare_T', ylog=True, formatsequence=['k-', 'r--'], xtitle = r'$R/R_{\rm NS}$', ytitle =  r'$T$, keV', multix = True)
# comparer('galia_F/BS_solution_F', 'titania_fidu/tireout01000', vnorm = -0.000173023, conf = 'FIDU')

    
def rcoolfun(geometry, mdot):
    '''
    calculates the cooling radius from the known geometry
    '''
    r = geometry[:,0] ; across = geometry[:,3] ; delta = geometry[:,5]

    f = delta**2/across * mdot - r
    ffun = interp1d(f, r, bounds_error = False)
    return ffun(0.)
    
def pds(infile='out/flux', binning=None, binlogscale=False):
    '''
    makes a power spectrum plot;
    input infile+'.dat' is an ascii, 2+column dat-file with an optional comment sign of #
    if binning is set, it should be the number of frequency bins; binlogscale makes frequency binning logarithmic
    '''
    lines = loadtxt(infile+".dat", comments="#", delimiter=" ", unpack=False)
    t=lines[:,0] ; l=lines[:,1]
    print("mean flux "+str(l.mean())+"+/-"+str(l.std()))
    # remove linear trend!
    linfit = polyfit(t, l, 1)
    f=fft.rfft((l-linfit[0]*t-linfit[1])/l.std(), norm="ortho")
    freq=fft.rfftfreq(size(t),t[1]-t[0])
    
    pds=abs(f)**2
    if ifplot:
        plots.pdsplot(freq, pds, outfile=infile+'_pds')
    
    # additional ascii output:
    fpds=open(infile+'_pds.dat', 'w')
    for k in arange(size(freq)-1)+1:
        fpds.write(str(freq[k])+' '+str(pds[k])+'\n')
    fpds.close()

    if binning != None:
        if binlogscale:
            binfreq=(freq.max()/freq[freq>0.].min())**(arange(binning+1)/double(binning))*freq[freq>0.].min()
            binfreq[0]=0.
        else:
            binfreq=linspace(freq[freq>0.].min(), freq.max(), binning+1)
        binflux=zeros(binning) ; dbinflux=zeros(binning)
        binfreqc=(binfreq[1:]+binfreq[:-1])/2. # bin center
        binfreqs=(binfreq[1:]-binfreq[:-1])/2. # bin size
        for k in arange(binning):
            win=((freq<binfreq[k+1]) & (freq>=binfreq[k]))
            binflux[k]=pds[win].mean() ; dbinflux[k]=pds[win].std()/sqrt(double(win.sum()))

        fpds=open(infile+'_pdsbinned.dat', 'w')
        for k in arange(binning):
            fpds.write(str(binfreq[k])+' '+str(binfreq[k+1])+' '+str(binflux[k])+' '+str(dbinflux[k])+'\n')
        fpds.close()
        if ifplot:
            plots.binplot_short(binfreqc, binfreqs, binflux, dbinflux, outfile=infile+'_pdsbinned')

def dynspec(infile='out/flux', ntimes=10, nbins=100, binlogscale=False, deline = False, ncol = 5, iffront = False, stnorm = False, fosccol = None, simfreq = None):
    '''
    makes a dynamic spectrum by making Fourier in each of the "ntimes" time bins. Fourier PDS is binned to "nbins" bins
    "ncol" is the number of data column in the input file (the last one is taken by default)
    
    '''
    lines = loadtxt(infile+".dat", comments="#", delimiter=" ", unpack=False)
    slines = shape(lines)
    if ncol >= slines[1]:
        ncol = -1
    t=lines[:,0] ; l=lines[:,ncol]
    if fosccol is not None:
        fosc = lines[:, fosccol]
    if simfreq is not None:
        l = l.mean() * sin(2.*pi*t*simfreq)*exp(-t)
    if iffront:
        xs = lines[:,1] # if we want to correlate the maximum with the mean front position
    else:
        xs = l # or, we can calculate a bin-average flux instead
    nsize=size(t)
    tbin=linspace(t.min(), t.max(), ntimes+1)
    tcenter=(tbin[1:]+tbin[:-1])/2.
    tsize = (tbin[1:]-tbin[:-1])/2.
    freq1=1./(t.max())*double(ntimes)/2. ; freq2=freq1*double(nsize)/double(ntimes)/2.
    if(binlogscale):
        binfreq=logspace(log10(freq1), log10(freq2), num=nbins+1)
    else:
        binfreq=linspace(freq1, freq2, nbins+1)
    binfreqc=(binfreq[1:]+binfreq[:-1])/2.
    pds2=zeros([ntimes, nbins]) ;   dpds2=zeros([ntimes, nbins])
    t2=zeros([ntimes+1, nbins+1], dtype=double)
    nbin=zeros([ntimes, nbins], dtype=double)
    binfreq2=zeros([ntimes+1, nbins+1], dtype=double)
    fmax = zeros(ntimes) ;   dfmax = zeros(ntimes)
    xmean = zeros(ntimes) ; xstd = zeros(ntimes)
    if fosccol is not None:
        foscmean = zeros(ntimes) ; foscstd = zeros(ntimes)
    fdyns=open(infile+'_dyns.dat', 'w')
    ffreqmax = open(infile+'_fmax.dat', 'w')
    for kt in arange(ntimes):
        wt=(t<tbin[kt+1]) & (t>=tbin[kt])
        lt=l[wt]
        pfit = polyfit(t[wt], lt, 1)
        if deline:
            fsp=fft.rfft((lt-pfit[0]*t[wt]-pfit[1]), norm="ortho")
        else:
            fsp=fft.rfft((lt-lt.mean()), norm="ortho")
        if stnorm:
            fsp /= lt.std()
        nt=size(lt)
        print("nt ="+str(nt))
        freq = fft.rfftfreq(nt, (t[wt].max()-t[wt].min())/double(nt))
        pds=abs(fsp*freq)**2
        t2[kt,:]=tbin[kt] ; t2[kt+1,:]=tbin[kt+1] 
        binfreq2[kt,:]=binfreq[:] ; binfreq2[kt+1,:]=binfreq[:] 
        for kb in arange(nbins):
            wb=((freq>binfreq[kb]) & (freq<=binfreq[kb+1]))
            nbin[kt,kb] = size(pds[wb])
            #            print("size(f) = "+str(size(freq)))
            #            print("size(pds) = "+str(size(pds)))
            pds2[kt, kb]=pds[wb].mean() ; dpds2[kt, kb]=pds[wb].std()
            # ascii output:
            fdyns.write(str(tcenter[kt])+' '+str(binfreq[kb])+' '+str(binfreq[kb+1])+' '+str(pds2[kt,kb])+' '+str(dpds2[kt,kb])+" "+str(nbin[kt,kb])+"\n")
        # finding maximum:
        nfmax = (pds2[kt,:]).argmax()
        fmax[kt] = (binfreq2[kt,nfmax]+binfreq2[kt+1,nfmax+1])/2. # frequency of the maximum
        dfmax[kt] = (-binfreq2[kt,nfmax]+binfreq2[kt+1,nfmax+1])/2. 
        ffreqmax.write(str(tcenter[kt])+" "+str(tsize[kt])+" "+str(fmax[kt])+" "+str(dfmax[kt])+"\n")
        xmean[kt] = xs[wt].mean() ; xstd[kt] = xs[wt].std()
        if fosccol is not None:
            foscmean[kt]=fosc[wt].mean() ; foscstd[kt]=fosc[wt].std()
    fdyns.close()
    ffreqmax.close()
    print(t2.max())
    if ifplot:
        frange = plots.plot_dynspec(t2,binfreq2, log10(pds2), outfile=infile+'_dyns', nbin=nbin)
        plots.errorplot(tcenter, tsize, fmax, dfmax, outfile = infile + '_ffmax', xtitle = '$t$, s', ytitle = '$f$, Hz')
        if iffront:
            # we need geometry:
            outdir = os.path.dirname(infile)
            geometry = loadtxt(outdir+"/geo.dat", comments="#", delimiter=" ", unpack=False)
            geo_r = geometry[:,0]  ; across = geometry[:,3]  ;   delta = geometry[:,5]
            deltafun = interp1d(geo_r, delta)
            delta_s = deltafun(xmean)
            acrossfun = interp1d(geo_r, across)
            across_s = acrossfun(xmean)
            # TODO: read from the conf. file
            rstar = 4.86 ; xirad = 1.5 ; m1 =1.4 ; mdot = 10. ; tscale = 4.92594e-06 * m1
            tth = tscale * mdot *  7.* sqrt(rstar * xmean) * delta_s**2/across_s * (1.+2.*across_s/delta_s**2)
            fth = 1./tth
            # 0.0227364 / xirad / sqrt(rstar*xmean)/rstar / mdot * (1./delta_s+2.*delta_s / across_s)**2 * 2.03e5/m1 # Hz
            goodx = (xmean > 3.*xstd) * (tcenter> tcenter[2])
            pfit, pcov = polyfit(log(xmean[goodx]), log(fmax[goodx]), 1, cov = True)
            print("dln(f)/dln(R_s) = "+str(pfit[0])+"+/-"+str(pcov[0,0]))
            if fosccol is not None:
                print(foscmean)
                fth = foscmean*2.
                fth[xmean > 10.] = sqrt(-1.)
            plots.errorplot(xmean, xstd, fmax, dfmax, outfile = infile + '_xfmax', xtitle = r'$R_{\rm shock}/R_{*}$', ytitle = '$f$, Hz', yrange = frange, addline = fth, xlog=True, ylog=False)
        else:
            plots.errorplot(xmean, xstd, fmax, dfmax, outfile = infile + '_lfmax', xtitle = r'$L/L_{\rm Edd}$', ytitle = '$f$, Hz')
            
#############################################
def fhist(infile = "out/flux"):
    '''
    histogram of flux distribution (reads a two-column ascii file)
    '''
    lines = loadtxt(infile+".dat", comments="#", delimiter=" ", unpack=False)
    t=lines[:,0] ; l=lines[:,1]
    nsize=size(t)
    fn, binedges = histogram(l, bins='auto')
    binc = (binedges[1:]+binedges[:-1])/2.
    bins = (binedges[1:]-binedges[:-1])/2.
    dfn = sqrt(fn)

    medianl = median(l)
    significant = (fn > (dfn*3.)) # only high signal-to-noize points
    w = significant * (binc>(medianl*3.))
    p, cov = polyfit(log(binc[w]), log(fn[w]), 1, w = 1./dfn[w], cov=True)
    print("median flux = "+str(medianl))
    print("best-fit slope "+str(p[0])+"+/-"+str(sqrt(cov[0,0])))

    if ifplot:
        plots.binplot(binedges, fn, dfn, fname=infile+"_hist", fit = exp(p[0]*log(binedges)+p[1]))

#####################################################################
def shock_hdf(n, infile = "out/tireout.hdf5", kleap = 5, uvcheck = False, uvcheckfile = 'uvcheck'):
    '''
    finds the position of the shock in a given entry of the infile
    kleap allows to measure the velocity difference using several cells
    '''
    entryname, t, l, r, sth, rho, u, v, qloss, glo = hdf.read(infile, n)
    n=size(r)
    #    v=medfilt(v, kernel_size=3)
    v1=savgol_filter(copy(v), 2*kleap+1, 1) # Savitzky-Golay filter
    #find maximal compression:
    dvdl = (v[kleap:]-v[:-kleap])/(l[kleap:]-l[:-kleap])
    wcomp = (dvdl).argmin()
    wcomp1 = maximum((wcomp-kleap),0)
    wcomp2 = minimum((wcomp+kleap),n-1)
    print("maximal compression found at r="+str((r[wcomp1]+r[wcomp2])/2.)+" +/- "+str((-r[wcomp1]+r[wcomp2])/2.))
    if isnan(r[wcomp]):
        print("t = "+str(t))
        print(dvdl.min(), dvdl.max())
        print(dvdl[wcomp])
        if ifplot:
            plots.someplots(r[1:], [v[1:], v1[1:], dvdl], name = "shocknan", xtitle=r'$r$', ytitle=r'$v$', xlog=False, formatsequence = ['k.', 'r-', 'b'])
        ii=input('r')

    ltot = simps(qloss, x=l)
    if wcomp1 > 2:
        lbelowshock = simps(qloss[0:wcomp1], x = l[0:wcomp1])
    else:
        lbelowshock = 0.

    if uvcheck:
        # let us check BS's equation (31):
        s= -rho * v
        uv = -u * v
        w = where(uv > 0.)
        w = (r > (r[wcomp1]/2.)) & (r< (r[wcomp2]*1.5))
        rstar = glo['rstar']
        if ifplot:
            plots.someplots(r[w], [uv[w], 0.75*(s/rstar/r)[w]], name = uvcheckfile,
                            xtitle=r'$r$', ytitle=r'$uv$',
                            xlog=False, ylog = True, formatsequence = ['k.', 'b-'],
                            vertical = (r[wcomp1]+r[wcomp2])/2.)
        
    return t, (r[wcomp1]+r[wcomp2])/2.,(-r[wcomp1]+r[wcomp2])/2., v[wcomp1], v[wcomp2], ltot, lbelowshock, u[0]
    #    return (r[wcomp:wcomp1]).mean(), r[wcomp:wcomp1],v[wcomp], v[wcomp1]
# v[wcomp], v[wcomp+1]

def shock_dat(n, prefix = "out/tireout", kleap = 1):
    '''
    finds the position of the shock and the velocity leap 
    from a given dat-file ID
    kleap allows to measure the velocity difference using several cells
    '''
    fname = prefix + hdf.entryname(n, ndig=5) + ".dat"
    lines = loadtxt(fname, comments="#")
    r = lines[:,0] ; v = lines[:,2]
    #find maximal compression:
    dvdl = (v[1:]-v[:-1])/(r[1:]-r[:-1])
    wcomp = (dvdl).argmin()
    #    print("maximal compression found at r="+str(r[wcomp])+".. "+str(r[wcomp+1])+"rstar")
    return (r[wcomp]+r[wcomp+1])/2., (r[wcomp+1]-r[wcomp])/2.,v[maximum(wcomp-kleap,00)], v[minimum(wcomp+1+kleap, size(r)-1)]
    
def multishock(n1, n2, dn, prefix = "out/tireout", dat = False, conf = None, kleap = 5, xest = 4.):
    '''
    draws the motion of the shock front with time, for a given set of HDF5 entries or ascii outputs
    '''
    if conf is None:
        conf = 'DEFAULT'
    rstar = config[conf].getfloat('rstar')
    tscale = config[conf].getfloat('tscale') * config[conf].getfloat('m1')
    m1 = config[conf].getfloat('m1')
    mu30 = config[conf].getfloat('mu30')
    mdot = config[conf].getfloat('mdot') * 4.*pi
    afac = config[conf].getfloat('afac')
    realxirad = config[conf].getfloat('xirad')
    b12 = 2.*mu30*(rstar*m1/6.8)**(-3) # dipolar magnetic field on the pole, 1e12Gs units
    umag = b12**2*2.29e6*m1

    n=arange(n1, n2, dn, dtype=int)
    t = zeros(size(n), dtype=double)
    s=arange(size(n), dtype=double)
    ds=arange(size(n), dtype=double)
    dv=arange(size(n), dtype=double)
    v2=arange(size(n), dtype=double)
    v1=arange(size(n), dtype=double)
    u0 =arange(size(n), dtype=double)
    lc_tot = arange(size(n), dtype=double) ; lc_part = arange(size(n), dtype=double)
    compression=arange(size(n), dtype=double)
    print(size(n))
    outdir = os.path.dirname(prefix)
    fluxlines = loadtxt(outdir+"/flux.dat", comments="#", delimiter=" ", unpack=False)
    geometry = loadtxt(outdir+"/geo.dat", comments="#", delimiter=" ", unpack=False)
    tf=fluxlines[:,0] ;
    ff=fluxlines[:,1]
    th = geometry[:,1] ; r = geometry[:,0]
    cthfun = interp1d(r/r[0], cos(th)) # we need a function allowing to calculate cos\theta (x)
    across0 = geometry[0,3]  ;   delta0 = geometry[0,5]
    BSgamma = (across0/delta0**2)/mdot*rstar / (realxirad/1.5)
    # umag is magnetic pressure
    BSeta = (8./21./sqrt(2.)*umag*3. * (realxirad/1.5))**0.25*sqrt(delta0)/(rstar)**0.125
    xs, BSbeta = bs.xis(BSgamma, BSeta, x0=xest, ifbeta = True)
    dt_BS = tscale * rstar**1.5 * bs.dtint(BSgamma, xs, cthfun)
    print("eta = "+str(BSeta))
    print("gamma = "+str(BSgamma))
    print("eta gamma^{1/4} = "+str(BSeta*BSgamma**0.25))
    print("beta = "+str(BSbeta))
    print("predicted shock position = "+str(xs))
    ii = input("xs")
    # spherization radius
    rsph =1.5*mdot/4./pi
    eqlum = mdot/rstar
    print("m1 = "+str(m1))
    print("mdot = "+str(mdot))
    print("rstar = "+str(rstar))
    # iterating to find the cooling radius
    rcool = rcoolfun(geometry, mdot)
    for k in arange(size(n)):
        if(dat):
            stmp, dstmp, v1tmp, v2tmp = shock_dat(n[k], prefix=prefix, kleap = kleap)
        else:
            ttmp, stmp, dstmp, v1tmp, v2tmp, ltot, lpart, u0tmp = shock_hdf(n[k], infile = prefix+".hdf5", kleap = kleap,
                                                                     uvcheck = (k == (size(n)-1)), uvcheckfile = outdir+"/uvcheck")
        s[k] = stmp ; ds[k] = dstmp
        v1[k] = v1tmp   ; v2[k] =  v2tmp
        dv[k] = v1tmp - v2tmp
        compression[k] = v2tmp/v1tmp
        lc_tot[k] = ltot ; lc_part[k] = lpart
        t[k] = ttmp
        u0[k] = u0tmp

    print("predicted shock position: xs = "+str(xs)+" (rstar)")
    print("cooling limit: rcool/rstar = "+str(rcool/rstar))
    print("flux array size "+str(size(lc_tot)))
    ff /= 4.*pi  ; eqlum /= 4.*pi ; lc_tot /= 4.*pi ; lc_part /= 4.*pi
    t *= tscale

    dt_current = tscale * rstar**1.5 * m1 * bs.dtint(BSgamma, s, cthfun)
    
    if(ifplot):
        ws=where((s>1.1) & (lc_part > lc_part.min()))
        n=ws
        plots.someplots(t[ws], [s[ws], s[ws]*0.+xs], name = outdir+"/shockfront", xtitle=r'$t$, s', ytitle=r'$R_{\rm shock}/R_*$', xlog=False, formatsequence = ['k-', 'r-', 'b:'], vertical = t.max()*0.9, verticalformatsequence = 'b:')        
        plots.someplots(lc_part[ws], [s[ws], s[ws]*0.+xs], name=outdir+"/fluxshock", xtitle=r'$L/L_{\rm Edd}$', ytitle=r'$R_{\rm shock}/R_*$', xlog= (lc_tot[ws].max()/lc_tot[ws].min()) > 10., ylog= (s[ws].max()/s[ws].min()> 10.), formatsequence = ['k-', 'r-', 'b-'], vertical = eqlum, verticalformatsequence = 'r-')
        # plots.someplots(t[ws], [ff[n], lc_part[ws], ff[n]*0.+eqlum], name = outdir+"/flux", xtitle=r'$t$, s', ytitle=r'$L/L_{\rm Edd}$', xlog=False, ylog=False, formatsequence = ['k:', 'k-', 'r-'])
        plots.someplots(t[ws], [-v1[ws], -v2[ws], sqrt(2./s[ws]/rstar), sqrt(2./s[ws]/rstar)/7.], name = outdir+"/vleap",xtitle=r'$t$, s', ytitle=r'$ v /c$', xlog=False, formatsequence = ['k-', 'b:', 'r-', 'r-'])
        plots.someplots(s[ws], [1./dt_current[ws], 1./(tscale * rstar**1.5 * s[ws]**3.5)], xtitle = r'$R_{\rm shock}/R_*$', xlog = True, ylog = True, formatsequence = ['ro', 'k-'], name = outdir + '/ux', ytitle = r'$f$, Hz')

    print("effective compression factor "+str(compression[isfinite(compression)].mean()))
    # ascii output
    fout = open(outdir+'/sfront.dat', 'w')
    #    foutflux = open(outdir+'/sflux.dat', 'w')
    fout.write("# time -- shock position -- downstream velocity -- upstream velocity -- total flux -- partial flux -- osc. freq.\n")
    for k in arange(size(n)):
        fout.write(str(t[k])+" "+str(s[k])+" "+str(v1[k])+" "+str(v2[k])+" "+str(lc_tot[k])+" "+str(lc_part[k])+" "+str(1./dt_current[k])+"\n")
    fout.close()
    fglo = open(outdir + '/sfrontglo.dat', 'w') # BS shock position and equilibrium flux
    fglo.write('# equilibrium luminosity -- BS shock front position / rstar -- Rcool position / rstar\n')

    if isscalar(xs):
        fglo.write(str(eqlum)+' '+str(xs)+' '+str(rcool/rstar)+'\n')
    else:
        fglo.write(str(eqlum)+' '+str(xs[0])+' '+str(rcool/rstar)+'\n')
    fglo.close()
    # last 10% average shock position
    wlaten = where(t > (t.max()*0.9))
    wlate = where(tf > (tf.max()*0.9))
    xmean = s[wlaten].mean() ; xrms = s[wlaten].std()+ds[wlaten].mean()
    print("s/RNS = "+str(xmean)+"+/-"+str(xrms)+"\n")
    fmean = ff[wlate].mean() ; frms = ff[wlate].std()
    print("flux = "+str(fmean)+"+/-"+str(frms)+"\n")
    print("OR flux = "+str(lc_tot[wlaten].mean())+".."+str(lc_part[wlaten].mean())+"\n")
    
        
###############################

# power-law fit to the decay tail
def tailfitfun(x, p, n, x0, y0):
    return ((x-x0)**2)**(p/2.)*n+y0

# exponential tail to the decay tail
def tailexpfun(x, xdec, n, x0, y0):
    return exp(-abs(x-x0)/xdec)*n+y0

def tailfit(prefix = 'out/flux', trange = None, ifexp = False, ncol = -1):
    '''
    fits the later shape of the light curve (or shock front position, if prefix is a sfront file, and ncol = 1), assuming it approaches equilibrium. 
    trange sets the range of time (s), ifexp switches between two fitting functions (power-law and exponential), ncol sets the column of the data file to be used. 
    '''
    fluxlines = loadtxt(prefix+".dat", comments="#", delimiter=" ", unpack=False)
    
    t=fluxlines[:,0] ; f=fluxlines[:,ncol]
    if(trange is None):
        t1 = t; f1 = f
    else:
        t1=t[(t>trange[0])&(t<trange[1])]
        f1=f[(t>trange[0])&(t<trange[1])]
    if ifexp:
        par, pcov = curve_fit(tailexpfun, t1, f1, p0=[t1.max()/5.,f1.max()-f1.min(), 0., f1.min()])
    else:
        par, pcov = curve_fit(tailfitfun, t1, f1, p0=[-2.,5., 0., f1.min()])
    if ifplot:
        if ifexp:
            plots.someplots(t, [f, tailexpfun(t, par[0], par[1], par[2], par[3]), t*0.+par[3]], name = prefix+"_fit", xtitle=r'$t$, s', ytitle=r'$L$', xlog=False, ylog=False, formatsequence=['k.', 'r-', 'g:'], yrange=[f[f>0.].min(), f.max()])
            plots.someplots(t, [f-par[3], tailexpfun(t, par[0], par[1], par[2], 0.)], name = prefix+"_dfit", xtitle=r'$t$, s', ytitle=r'$\Delta L$', formatsequence=['k.', 'r-'], ylog = True, xlog = False)
        else:
            plots.someplots(t, [f, tailfitfun(t, par[0], par[1], par[2], par[3]), t*0.+par[3]], name = prefix+"_fit", xtitle=r'$t$, s', ytitle=r'$L$', xlog=False, ylog=False, formatsequence=['k.', 'r-', 'g:'], yrange=[f[f>0.].min(), f.max()])
            plots.someplots(t, [f-par[3], tailfitfun(t, par[0], par[1], par[2], 0.)], name = prefix+"_dfit", xtitle=r'$t$, s', ytitle=r'$\Delta L$', formatsequence=['k.', 'r-'], ylog = True, xlog = False)
    
    if ifexp:
        print("decay time = "+str(par[0])+"+/-"+str(sqrt(pcov[0,0])))
    else:
        print("slope ="+str(par[0])+"+/-"+str(sqrt(pcov[0,0])))
    print("y0 ="+str(par[3])+"+/-"+str(sqrt(pcov[3,3])))

##################################################################
def mdotmap(n1, n2, step,  prefix = "out/tireout", ifdat = False, conf='DEFAULT'):
    # reconstructs the mass flow
    # reading geometry:
    geofile = os.path.dirname(prefix)+"/geo.dat"
    #    fluxfile = os.path.dirname(prefix)+"/flux.dat"
    #    fluxlines = loadtxt(fluxfile, comments="#")
    #    tar=fluxlines[:,0]
    print(geofile)
    r, theta, alpha, across, l, delta = geo.gread(geofile) 
    nr = size(r) 
    indices = arange(n1, n2, step)
    nind = size(indices)
    md2 = zeros([nind, nr], dtype=double)
    t2 = zeros([nind, nr], dtype=double)
    r2 = zeros([nind, nr], dtype=double)   
    
    for k in arange(nind): # arange(n1, n2, step):
        hname = prefix + ".hdf5"
        if(ifdat):
            fname = prefix + hdf.entryname(indices[k], ndig=5) + ".dat"
            print(fname)
            lines = loadtxt(fname, comments="#")
            r = lines[:,0] ; rho = lines[:,1] ; v = lines[:,2]
            t=tar[indices[k]]
            mdot = config[conf].getfloat('mdot') * 4.*pi
        else:
            entryname, t, l, r, sth, rho, u, v, qloss, glo = hdf.read(hname, indices[k])
            mdot = glo['mdot'] * 4.*pi
        md2[k, :] = (rho * v * across)[:]
        t2[k, :] = t  ;     r2[k, :] = r[:]
        tscale = config[conf].getfloat('tscale')

    # ascii output:
    fmap = open(prefix+"_mdot.dat", "w")
    for k in arange(k):
        for kr in arange(nr):
            fmap.write(str(t2[k, kr])+" "+str(r2[k, kr])+" "+str(md2[k, kr])+"\n")
    fmap.close()
    if(ifplot):
        # graphic output
        nlev=30
        mdmean = -md2.mean(axis=0)
        plots.somemap(r2, t2*tscale, -md2/mdot, name=prefix+"_mdot", levels = (3.*arange(nlev)/double(nlev-2)-1.),
                      inchsize = [4,6], cbtitle = r'$s/\dot{M}_{\rm out}$')
        plots.someplots(r, [mdmean/(4.*pi), mdmean*0.+mdot/(4.*pi)], name=prefix+"_mdmean",
                        xtitle='$R/R_*$', ytitle=r"$sc^2/L_{\rm Edd}$", formatsequence=['k.', 'r-'])
        
        
def taus(n, prefix = 'out/tireout', ifhdf = True, conf = 'DEFAULT'):
    '''
    calculates the optical depths along and across the flow
    '''

    rstar = config[conf].getfloat('rstar')
    m1 = config[conf].getfloat('m1')
    mu30 = config[conf].getfloat('mu30')
    mdot = config[conf].getfloat('mdot') * 4.*pi
    afac = config[conf].getfloat('afac')
    realxirad = config[conf].getfloat('xirad')

    geofile = os.path.dirname(prefix)+"/geo.dat"
    print(geofile)
    r, theta, alpha, across, l, delta = geo.gread(geofile) 
    if(ifhdf):
        hname = prefix + ".hdf5"
        entryname, t, l, r, sth, rho, u, v, qloss, glo = hdf.read(hname, n)
    else:
        entryname = hdf.entryname(n, ndig=5)
        fname = prefix + entryname + ".dat"
        lines = loadtxt(fname, comments="#")
        rho = lines[:,1]
    taucross = delta * rho  # across the flow
    dr = (r[1:]-r[:-1])  ;   rc = (r[1:]+r[:-1])/2.
    taualong = (rho[1:]+rho[:-1])/2. * dr
    taucrossfun = interp1d(r, taucross, kind = 'linear')
    if(ifplot):
        plots.someplots(rc/rstar, [taucrossfun(rc), taualong], name = prefix+"_tau", xtitle=r'$r/R_{\rm NS}$', ytitle=r'$\tau$', xlog=True, ylog=True, formatsequence=['k-', 'r-'])

def virialratio(n, prefix = 'out/tireout', ifhdf = True):
    '''
    checks the virial relations in the flow
    '''
    geofile = os.path.dirname(prefix)+"/geo.dat"
    print(geofile)
    r, theta, alpha, across, l, delta = geo.gread(geofile) 
    if(ifhdf):
        hname = prefix + ".hdf5"
        entryname, t, l, r, sth, rho, u, v, qloss, glo = hdf.read(hname, n)
    else:
        entryname = hdf.entryname(n, ndig=5)
        fname = prefix + entryname + ".dat"
        lines = loadtxt(fname, comments="#")
        rho = lines[:,1]
    egrav = trapz(rho * across / r, x = l)
    ethermal = trapz(u * across, x = l)
    ebulk = trapz(rho * across * v**2/2., x = l)

    return t, egrav, ethermal, ebulk, (ethermal+ebulk)/egrav

def virialtest(n1, n2, prefix = 'out/tireout'):
    '''
    tests virial relations as a function of time
    '''
    nar = arange(n2-n1)+n1

    virar = zeros(n2-n1) ; tar = zeros(n2-n1)
    
    for k in arange(n2-n1):
        t, egrav, ethermal, ebulk, viratio = virialratio(nar[k], prefix = prefix)
        virar[k] = viratio ; tar[k] = t

    if(ifplot):
        plots.someplots(tar, [virar], name = prefix+"_vire", xtitle=r'$t$', ytitle=r'$E_{\rm k} / E_{\rm g}$', xlog=False, ylog=False, formatsequence=['k-'])

def filteredflux(hfile, n1, n2, rfraction = 0.9, conf = 'DEFAULT'):
    '''
    calculates the flux excluding several outer points affected by the outer BC
    hfile is the input HDF5 file
    n1 is the number of the first entry
    n2 is the last one
    rfraction is the rangle of radii where the flux is being calculated
    '''
    geofile = os.path.dirname(hfile)+"/geo.dat"
    r, theta, alpha, across, l, delta = geo.gread(geofile)
    wr = r < (r.max()*rfraction)

    tscale = config[conf].getfloat('tscale') * config[conf].getfloat('m1')

    lint = zeros(n2-n1)
    ltot = zeros(n2-n1)
    tar = zeros(n2-n1)
    
    for k in arange(n2-n1)+n1:
        entryname, t, l, r, sth, rho, u, v, qloss, glo = hdf.read(hfile, k)
        mdot = glo['mdot']
        lint[k] = simps(qloss[wr], x=l[wr])
        ltot[k] = simps(qloss, x=l)
        tar[k] = t
    ltot /= 4.*pi ; lint /= 4.*pi # convert to Eddington units
    tar *= tscale
    if(ifplot):
        # overplotting with the total flux
        plots.someplots(tar, [lint, ltot, ltot-lint, lint*0.+mdot*0.2], xlog=False, formatsequence = ['k-', 'g--', 'b--', 'r-'], xtitle='t, s', ytitle=r'$L/L_{\rm Edd}$', name= os.path.dirname(hfile)+'/cutflux')

    # ascii output:
    fout = open(os.path.dirname(hfile)+"/cutflux.dat", "w")
    for k in arange(n2-n1)+n1:
        fout.write(str(tar[k])+" "+str(lint[k])+" "+str(ltot[k])+"\n")
        fout.flush()
    fout.close()
    # flux during the last 10% of the curve:
    w = (tar > (tar.max()*0.9))
    ffilteredmean = lint[w].mean()
    fmean = ltot[w].mean()
    fstd = ltot[w].std()
    print("Fmean = "+str(fmean)+"+/-"+str(fstd)+" ("+str(fmean-ffilteredmean)+")")
    
    
def massplot(prefix = "out/tireout"):
    geofile = os.path.dirname(prefix)+"/geo.dat"
    tscale = config['DEFAULT'].getfloat('tscale')
    massscale = config['DEFAULT'].getfloat('massscale')
    print(geofile)
    r, theta, alpha, across, l, delta = geo.gread(geofile) 
    totfile = os.path.dirname(prefix)+"/totals"
    lines = loadtxt(totfile+".dat", comments="#", delimiter=" ", unpack=False)
    tene = lines[:,0] ;  mass = lines[:,1]

    print(umag)
    mcol = across[0] * umag * rstar**2 * 2.

    tfilter = tene < 0.05
    tene = tene[tfilter]
    mass = mass[tfilter]

    mass *= massscale/1e16
    mcol *= massscale/1e16

    if ifplot:
        plots.someplots(tene, [mass, mdot * tene/tscale * massscale/1e16+mass[0], mass*0. + mcol], formatsequence = ['k-', 'r:', 'g--'], name = os.path.dirname(prefix)+"/masstest", xtitle='t, s', ytitle=r'$M$, $10^{16}$g', xlog = False, ylog = False)


        
def lplot():

    prefices = ['titania_mdot1', 'titania_mdot3', 'titania_fidu', 'titania_mdot30', 'titania_dhuge', 'titania_nod']

    confs = ['M1', 'M3', 'FIDU', 'M30', 'DHUGE', 'NOD']

    xests = [1.5, 2., 4., 8., 4., 4.]
    
    npref = size(prefices)

    lrad = zeros(npref) ; dlrad = zeros(npref) ; ltot = zeros(npref) ; gammas = zeros(npref) ; betas = zeros(npref)

    for k in arange(npref):
        rstar = config[confs[k]].getfloat('rstar')
        m1 = config[confs[k]].getfloat('m1')
        mu30 = config[confs[k]].getfloat('mu30')
        mdot = config[confs[k]].getfloat('mdot') * 4.*pi
        afac = config[confs[k]].getfloat('afac')
        realxirad = config[confs[k]].getfloat('xirad')
        b12 = 2.*mu30*(rstar*m1/6.8)**(-3) # dipolar magnetic field on the pole, 1e12Gs units
        umag = b12**2*2.29e6*m1
        geometry = loadtxt(prefices[k]+"/geo.dat", comments="#", delimiter=" ", unpack=False)
        across0 = geometry[0,3]  ;   delta0 = geometry[0,5]
        BSgamma = (across0/delta0**2)/mdot*rstar / (realxirad/1.5)
        # umag is magnetic pressure
        BSeta = (8./21./sqrt(2.)*umag*3. * (realxirad/1.5))**0.25*sqrt(delta0)/(rstar)**0.125
        xs, BSbeta = bs.xis(BSgamma, BSeta, x0=xests[k], ifbeta = True)

        frontfile = prefices[k]+'/sfront'
        frontlines = loadtxt(frontfile+'.dat', comments="#", delimiter=" ", unpack=False)

        f = frontlines[:,5] # partial flux from below the shock
        nt = size(f)
        lrad[k] = f[round(nt*0.9):].mean()
        dlrad[k] = f[round(nt*0.9):].std()
        ltot[k] = mdot * 0.205 / 4./pi
        gammas[k] = BSgamma
        betas[k] = BSbeta
        print(ltot[k])

    plots.errorplot(1./gammas, gammas*0., lrad/ltot, dlrad/ltot, outfile = 'bsfig2',
                    xtitle = r'$\gamma^{-1}$', ytitle = r'$L_{\rm s}/L_{\rm tot}$', addline  = 1.-betas, xlog = True, pointlabels = confs)
