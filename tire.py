from scipy.integrate import *
from scipy.interpolate import *

import numpy.random
from numpy.random import rand
from numpy import *
# import time
import os
import os.path
import imp
import sys

if(size(sys.argv)>1):
    print("launched with arguments "+str(', '.join(sys.argv)))
    # new conf file
    conf=sys.argv[1]
else:
    conf = 'globals'
'''
A trick (borrowed from where???) that allows to load an arbitrary configuration file instead of the standard "globals.py"
'''
fp, pathname, description = imp.find_module(conf)
imp.load_module('globals', fp, pathname, description)
fp.close()

from globals import *

# loading local modules:
if ifplot:
    import plots
import hdfoutput as hdf
import bassun as bs
import solvers as solv
from sigvel import *

from timer import Timer
timer = Timer(["total", "step", "io"],
              ["main", "flux", "solver", "toprim", "velocity", "sources"])

#
def regularize(u, rho):
    '''
    if internal energy goes below ufloor, we heat the matter up artificially
    '''
    u1=u-ufloor ; rho1=rho-rhofloor
    return (u1+fabs(u1))/2.+ufloor, (rho1+fabs(rho1))/2.+rhofloor

#
def quasirelfunction(v, v0):
    '''
    this function matches f(v)=v below v0 and approaches 1 at v \to 0 
    '''
    sv0 = sqrt(1.+v0**2) ; sv = sqrt(1.+v**2)
    a = (1.+2.*v0**2)/sv0 ; b= -v0**3/sv0
    return (a*abs(v)+b)/sv*sign(v)

# speed of sound multiplier (see Chandrasekhar 1967 or Johnson 2008):
def Gamma1(gamma, beta):
    g1 = gamma - 1.
    return beta + 9. * g1 * (beta-4./3.)**2/(beta+12.*g1 * (1.-beta))

# smooth factor for optical depth
def taufun(tau):
    '''
    calculates 1-exp(-x) in a reasonably smooth way trying to avoid round-off errors for small and large x
    '''
    wtrans = where(tau<taumin)
    wopaq = where(tau>taumax)
    wmed = where((tau>=taumin) & (tau<=taumax))
    tt = tau*0.
    if(size(wtrans)>0):
        tt[wtrans] = (tau[wtrans]+abs(tau[wtrans]))/2.
    if(size(wopaq)>0):
        tt[wopaq] = 1.
    if(size(wmed)>0):
        tt[wmed] = 1. - exp(-tau[wmed])
    return tt

def tratfac(x):
    '''
    the correction factor used when local thermal time scales are small
    '''
    xmin = taumin ; xmax = taumax # limits the same as for optical depth
    tt=x*0.
    w1 = where(x<= xmin) ;  w2 = where(x>= xmax) ; wmed = where((x < xmax) & (x > xmin))
    if(size(w1)>0):
        tt[w1] = 1.
    if(size(w2)>0):
        tt[w2] = 1./x[w2]
    if(size(wmed)>0):
        tt[wmed] = (1.-exp(-x[wmed]))/x[wmed]
    wnan=where(isnan(x))
    if(size(wnan)>0):
        tt[wnan] = 0.
        #    print("trat = "+str(x.min())+".."+str(x.max()))
    return tt

# pressure ratios:
def Fbeta(rho, u):
    '''
    calculates a function of 
    beta = pg/p from rho and u (dimensionless units)
    F(beta) itself is F = beta / (1-beta)**0.25 / (1-beta/2)**0.75
    '''
    beta = rho*0.+1.
    wpos=where(u>ufloor)
    if(size(wpos)>0):
        beta[wpos]=betacoeff * rho[wpos] / u[wpos]**0.75
    return beta 

def betafun_define():
    '''
    defines the function to calculate beta as a function of rho/u**0.75
    '''
    bepsilon = 1e-8 ; nb = 1e4
    b1 = 0. ; b2 = 1.-bepsilon
    b = (b2-b1)*arange(nb+1)/double(nb)+b1
    fb = b / (1.-b)**0.25 / (1.-b/2.)**0.75
    bfun = interp1d(fb, b, kind='linear', bounds_error=False, fill_value=1.)
    return bfun

# define once and globally
betafun = betafun_define() # defines the interpolated function for beta

##############################################################################
def geometry(r, writeout=None):
    '''
    computes all the geometrical quantities. Sufficient to run once before the start of the simulation.
    Output: sin(theta), cos(theta), sin(alpha), cos(alpha), tangential cross-section area, 
    and l (zero at the surface, growing with radius)
    adding nontrivial writeout key allows to write the geometry to an ascii file 
    '''
    #    theta=arcsin(sqrt(r/r_e))
    #    sth=sin(theta) ; cth=cos(theta)
    sth=sqrt(r/r_e) ; cth=sqrt(1.-r/r_e) # OK
    across=4.*pi*afac*dr_e*r_e*(r/r_e)**3/sqrt(1.+3.*cth**2) # follows from Galja's formula (17)
    alpha=arctan((cth**2-1./3.)/sth/cth) # Galja's formula (3)
    sina=sin(alpha) ; cosa=cos(alpha)
    l=cumtrapz(sqrt(1.+3.*cth**2)/2./cth, x=r, initial=0.) # coordinate along the field line
    delta = r * sth/sqrt(1.+3.*cth**2) * dr_e/r_e
    # transverse thickness of the flow (Galya's formula 17)
    # dl diverges near R=Re, hence the maximal radius should be smaller than Re
    # ascii output:
    if(writeout != None):
        theta=arctan(sth/cth)
        fgeo=open(writeout, 'w')
        fgeo.write('# format: r -- theta -- alpha -- across -- l -- delta \n')
        for k in arange(size(l)):
            fgeo.write(str(r[k])+' '+str(theta[k])+' '+str(alpha[k])+' '+str(across[k])+' '+str(l[k])+' '+str(delta[k])+'\n')
        fgeo.close()
    
    return sth, cth, sina, cosa, across, l, delta

def cons(rho, v, u, across, r, sth):
    '''
    computes conserved quantities from primitives
    '''
    m=rho*across # mass per unit length
    s=m*v # momentum per unit length
    e=(u+rho*(v**2/2.- 1./r - 0.5*(omega*r*sth)**2))*across  # total energy (thermal + mechanic) per unit length
    return m, s, e

def diffuse(rho, urad, dl, across_half):
    '''
    radial energy diffusion;
    calculates energy flux contribution already at the cell boundary
    '''
    rho_half = (rho[1:]+rho[:-1])/2. # ; v_half = (v[1:]+v[:-1])/2.  ; u_half = (u[1:]+u[:-1])/2.
    rtau_left = rho[1:] * dl # optical depths along the field line, to the left of the cell boundaries
    rtau_right = rho[:-1] * dl # -- " -- to the right -- " --
    dul_half = across_half*((urad/(rho+1.))[1:]*(1.-exp(-rtau_left/2.))-(urad/(rho+1.))[:-1]*(1.-exp(-rtau_right/2.)))/dl/3. # radial diffusion
    # introducing exponential factors helps reduce the numerical noise from rho variations
    return -dul_half

def fluxes(rho, v, u, across, r, sth):
    '''
    computes the fluxes of conserved quantities, given primitives; 
    radiation diffusion flux is not included, as it is calculated at halfpoints
    '''
    s=rho*v*across # mass flux (identical to momentum per unit length -- can we use it?)
    beta = betafun(Fbeta(rho, u))
    press = u/3./(1.-beta/2.)
    p=across*(rho*v**2+press) # momentum flux
    fe=across*v*(u+press+(v**2/2.-1./r-0.5*(omega*r*sth)**2)*rho) # energy flux without diffusion
    return s, p, fe

def sources(rho, v, u, across, r, sth, cth, sina, cosa, ltot=0., dt=None):
    '''
    computes the RHSs of conservation equations
    no changes in mass
    momentum injection through gravitational and centrifugal forces
    energy losses through the surface
    outputs: dm, ds, de, and separately the amount of energy radiated per unit length per unit time ("flux")
    additional output: trat = Q dt / U
    '''
    #  sinsum=sina*cth+cosa*sth # cos( pi/2-theta + alpha) = sin(theta-alpha)
    tau = rho*across/(4.*pi*r*sth*afac)
    taufac = taufun(tau)    # 1.-exp(-tau)
    gamefac = taufac/tau
    gamedd = eta * ltot * gamefac 
    force = (-(sina*cth+cosa*sth)/r**2*(1.-gamedd)+omega**2*r*sth*cosa)*rho*across #*taufac
    beta = betafun(Fbeta(rho, u))
    urad = u * (1.-beta)/(1.-beta/2.)
    qloss = urad/(xirad*tau+1.)*8.*pi*r*sth*afac*taufac  # diffusion approximations; energy lost from 4 sides
    irradheating = heatingeff * gamedd * (sina*cth+cosa*sth)/r**2*8.*pi*r*sth*afac*taufac # photons absorbed by the matter also heat it
    if(dt is not None):            
        trat = qloss * dt / u
        qloss *= tratfac(trat)
    else:
        trat = u*0. +1.
    dudt = v*force-qloss+irradheating
    return rho*0., force, dudt, qloss, trat

def toprim(m, s, e, across, r, sth):
    '''
    convert conserved quantities to primitives
    '''
    rho=m/across
    v=s/m
    wrel = where(fabs(v)>vmax)
    if(size(wrel)>0):
        v[wrel] =  quasirelfunction(v[wrel], vmax) # equal to vmax when v[wrel]=vmax, approaching 1 at large values 
    # v[wrel]*sqrt((1.+vmax**2)/(1.+v[wrel]**2))
    if(m.min()<mfloor):
        print("toprim: m.min = "+str(m.min()))
        print("... at "+str(r[m.argmin()]))
        #   exit(1)
    #    v=s*0.
    #    v[rho>rhofloor]=(s/m)[rho>rhofloor]
    #    v=v/sqrt(1.+v**2)
    u=(e-m*(v**2/2.-1./r-0.5*(r*sth*omega)**2))/across
    umin = u.min()
    #    if(rho.min() < rhofloor):
    #        print("rhomin = "+str(rho.min()))
    #        print("mmin = "+str(m.min()))
        # exit(1)
        #    u[u<=ufloor]=0.
    beta = betafun(Fbeta(rho, u))
    press = 3.*(1.-beta/2.) * u
    return rho, v, u, u*(1.-beta)/(1.-beta/2.), beta, press

def main_step(m, s, e, l_half, s_half, p_half, fe_half, dm, ds, de, dt, r, sth, across, dlleft, dlright, g1):
    '''
    main advance in a dt step
    input: three densities, l (midpoints), three fluxes (midpoints), three sources, timestep, r, sin(theta), cross-section
    output: three new densities
    includes boundary conditions!
    '''
    #    print("main_step: mmin = "+str(m.min()))
    nl=size(m)
    m1=zeros(nl) ; s1=zeros(nl); e1=zeros(nl)
    m1[1:-1] = m[1:-1]+ (-(s_half[1:]-s_half[:-1])/(l_half[1:]-l_half[:-1]) + dm[1:-1]) * dt
    s1[1:-1] = s[1:-1]+ (-(p_half[1:]-p_half[:-1])/(l_half[1:]-l_half[:-1]) + ds[1:-1]) * dt
    e1[1:-1] = e[1:-1]+ (-(fe_half[1:]-fe_half[:-1])/(l_half[1:]-l_half[:-1]) + de[1:-1] ) * dt 

    # enforcing boundary conditions:
    if(m[0]>mfloor):
        mdot0 = mdotsink # sink present when mass density is positive at the inner boundary
        edot0 = -mdotsink*e[0]/m[0] # energy sink 
    else:
        mdot0 = 0.
        edot0 = 0.
    m1[0] = m[0] + (-(s_half[0]-(-mdot0))/dlleft+dm[0]) * dt # mass flux is zero through the inner boundary
    m1[-1] = m[-1] + (-(-mdot-s_half[-1])/dlright+dm[-1]) * dt  # inflow set to mdot (global)
    #    print("main_step: mmin1 = "+str(m1.min()))
    #    print("... at  = "+str(r[m1.argmin()]))
    # this effectively limits the outer velocity from above
    #    if(m1[-1]< (mdot / abs(vout))):
    #        m1[-1] = mdot / abs(vout)
    s1[0] = -mdot0
    s1[-1] = -mdot 
    vout_current = s1[-1]/m1[-1]
    if galyamode:
        e1[0] = across[0] * umag + m1[0] * (-1./r[0]) # *(u+rho*(v**2/2.- 1./r - 0.5*(omega*r*sth)**2))*across
    else:
        if coolNS:
            e1[0] = - (m1/r)[0]
        else:
            e1[0] = e[0] + (-(fe_half[0]-edot0)/dlleft+de[0]) *dt #  energy flux is zero
    if ufixed:
        e1[-1] = (m1*(vout_current**2/2.-1./r-0.5*(r*sth*omega)**2)+across*umagout/(g1-1.))[-1] # fixing internal energy at the outer rim 
    else:
        edot = -mdot*(vout_current**2/2.-1./r-0.5*(r*sth*omega)**2)[-1]+across[-1]*vout_current*umagout * (g1/(g1-1.))[-1] # energy flux from the right boundary 
        e1[-1] = e[-1] + (-(edot-fe_half[-1])/dlright + de[-1])  * dt  # energy inlow
        #    s1[0] = s[0] + (-(p_half[0]-pdot)/(l_half[1]-l_half[0])+ds[0]) * dt # zero velocity, finite density (damped)
    # what if we get negative mass?
    wneg=where(m1<mfloor)
    m1 = maximum(m1, mfloor)
    if(size(wneg)>0):
        # exit()
        s1[wneg] = (m1 * s/m)[wneg]
        e1[wneg] = (e1 * e/m)[wneg]    
    return m1, s1, e1

################################################################################
def alltire():
    '''
    the main routine bringing all together.
    '''
    timer.start("total")

    # if the outpur directory does not exist:
    if not os.path.exists(outdir):
        os.makedirs(outdir)

    sthd=1./sqrt(1.+(dr_e/r_e)**2) # initial sin(theta)
    rmax=r_e*sthd # slightly less then r_e 
    r=((2.*(rmax-rstar)/rstar)**(arange(nx0)/double(nx0-1))+1.)*(rstar/2.) # very fine radial mesh
    sth, cth, sina, cosa, across, l, delta = geometry(r) # radial-equidistant mesh
    l += r.min() # we are starting from a finite radius
    if(logmesh):
        luni=exp(linspace(log(l.min()), log(l.max()), nx, endpoint=False)) # log(l)-equidistant mesh
    else:
        luni=linspace(l.min(), l.max(), nx, endpoint=False)
    l -= r.min() ; luni -= r.min()
    luni_half=(luni[1:]+luni[:-1])/2. # half-step l-equidistant mesh
    rfun=interp1d(l,r, kind='linear') # interpolation function mapping l to r
    rnew=rfun(luni) # radial coordinates for the  l-equidistant mesh
    sth, cth, sina, cosa, across, l, delta = geometry(rnew, writeout=outdir+'/geo.dat') # all the geometric quantities for the l-equidistant mesh
    r=rnew # set a grid uniform in l=luni
    r_half=rfun(luni_half) # half-step radial coordinates
    sth_half, cth_half, sina_half, cosa_half, across_half, l_half, delta_half = geometry(r_half) # mid-step geometry in r
    l_half+=l[1]/2. # mid-step mesh starts halfstep later
    dlleft = 2.*(l_half[1]-l_half[0])-(l_half[2]-l_half[1])
    dlright = 2.*(l_half[-1]-l_half[-2])-(l_half[-2]-l_half[3])
    dl=l[1:]-l[:-1] # cell sizes 
    
    # testing bassun.py
    print("delta = "+str((across/(4.*pi*afac*r*sth))[0]))
    print("delta = "+str((sth*r/sqrt(1.+3.*cth**2))[0] * dr_e/r_e))
    print("delta = "+str(delta[0]))
    BSgamma = (across/delta**2)[0]/mdot*rstar
    BSeta = (8./21./sqrt(2.)*umag)**0.25*sqrt(delta[0])/(rstar)**0.125
    print("BS parameters:")
    print("   gamma = "+str(BSgamma))
    print("   eta = "+str(BSeta))
    x1 = 1. ; x2 = 1000. ; nxx=1000
    xtmp=(x2/x1)**(arange(nxx)/double(nxx))*x1
    if(ifplot):
        plots.someplots(xtmp, [bs.fxis(xtmp, BSgamma, BSeta, 3.)], name='fxis', ytitle=r'$F(x)$')
    xs = bs.xis(BSgamma, BSeta)
    print("   xi_s = "+str(xs))
    # input("BS")
    # magnetic field energy density:
    umagtar = umag * (1.+3.*cth**2)/4. * (rstar/r)**6
    # initial conditions:
    m=zeros(nx) ; s=zeros(nx) ; e=zeros(nx)
    vinit=vout*(r-rstar)/(r+rstar) *sqrt(r_e/r) # initial velocity
    #    m=mdot/fabs(vout*sqrt(r_e/r)) # mass distribution
    #    m0=m 
    #    s+=vinit*m
    #    e+=(vinit**2/2.-1./r-0.5*(r*sth*omega)**2)*m+3.*umagout*across * (1.+0.01*rand(size(r)))+vout**2*m
    rho = abs(mdot) / (abs(vout)+abs(vinit)) / across
    u = 3.*umagout+(rho/rho[-1])*0.01/r
    print("U = "+str(u.min())+" to "+str(u.max()))
    m, s, e = cons(rho, vinit, u, across, r, sth)

    rho1, v1, u1, urad, beta, press = toprim(m, s, e, across, r, sth) # primitive from conserved
    print(str((rho-rho1).std())) 
    print(str((vinit-v1).std()))
    print(str((u-u1).std())) # accuracy 1e-14
    print("primitive-conserved")
    print("rhomin = "+str(rho.min())+" = "+str(rho1.min()))
    #    input("P")
    m0=m
    
    t=0.;  tstore=0.  ; nout=0

    # if we want to restart from a stored configuration
    # works so far correctly ONLY if the mesh is identical!
    if(ifrestart):
        if(ifhdf):
            # restarting from a HDF5 file
            entryname, t, l, r, sth, rho, u, v = hdf.read(restartfile, restartn)
            tstore = t
            print("restarted from file "+restartfile+", entry "+entryname)
        else:
            # restarting from an ascii output
            ascrestartname = restartprefix + hdf.entryname(restartn, ndig=5) + ".dat"
            lines = loadtxt(ascrestartname, comments="#")
            rho = lines[:,1] ; v = lines[:,2] ; u = lines[:,3] * umagtar
            # what about t??
            print("restarted from ascii output "+ascrestartname)
        r *= rstar
        m, s, e = cons(rho, v, u, across, r, sth)
        nout = restartn
        
    dlmin=(l_half[1:]-l_half[:-1]).min()
    dt = dlmin*0.25
    print("dt = "+str(dt))
    #    ti=input("dt")
    
    ltot=0. # estimated total luminosity
    if(ifrestart):
        fflux=open(outdir+'/'+'flux.dat', 'a')
        ftot=open(outdir+'/'+'totals.dat', 'a')
    else:
        fflux=open(outdir+'/'+'flux.dat', 'w')
        ftot=open(outdir+'/'+'totals.dat', 'w')

    if(ifhdf):
        hname = outdir+'/'+'tireout.hdf5'
        hfile = hdf.init(hname, l, r, sth, cth) # , m1, mdot, eta, afac, re, dre, omega)
    
    timer.start("total")
    while(t<tmax):
        # first make a preliminary half-step
        timer.start_comp("toprim")
        mprev=m ; sprev=s ; eprev=e
        #        print("mmin = "+str(m.min()))
        rho, v, u, urad, beta, press = toprim(m, s, e, across, r, sth) # primitive from conserved
        #        print("rhomin = "+str(rho.min()))
        #        input("M")
        u,rho = regularize(u,rho) 
        dt = dlmin*0.25/(1.+(u/rho)+fabs(v)).max()
        #        print("dt = "+str(dt))
        #        wneg = (u<ufloor)
        # rho[wneg] = rhofloor ; u[wneg] = ufloor
        timer.stop_comp("toprim")
        timer.start_comp("flux")
        #        dul = diffuse(rho, urad, dl, across_half)
        s, p, fe = fluxes(rho, v, u, across, r, sth)
        #    fe += -dul # adding diffusive flux 
        timer.stop_comp("flux")
        timer.start_comp("velocity")
        g1 = Gamma1(5./3., beta)
        cs=sqrt(g1*press/(rho+0.*(u+press))) # slightly under-estimating the SOS to get stable signal velocities; exact for u<< rho
        vl, vm, vr = sigvel_isentropic(v, cs, g1)        
        timer.stop_comp("velocity")
        timer.start_comp("solver")
        s_half, p_half, fe_half =  solv.HLLC([s, p, fe], [m, s, e], vl, vr, vm)
        dul_half = diffuse(rho, urad, dl, across_half)
        fe_half += dul_half
        # solv.HLLC([s, p, fe], [m, s, e], vl, vr, vstar)
        timer.stop_comp("solver")
        timer.start_comp("sources")
        dm, ds, de, flux, trat = sources(rho, v, u, across, r, sth, cth, sina, cosa,ltot=ltot)
        ltot=simps(flux, x=l) # no difference
        heat=simps(de+flux, x=l)
        timer.stop_comp("sources")
        timer.start_comp("main")
        m1, s1, e1 = main_step(m, s, e, l_half, s_half, p_half, fe_half, dm, ds, de, dt/2., r, sth, across, dlleft, dlright, g1)
        timer.stop_comp("main")
        timer.lap("step")
        # second take, real step
        timer.start_comp("toprim")
        rho1, v1, u1, urad1, beta1, press1 = toprim(m1, s1, e1, across, r, sth) # primitive from conserved
        u1, rho1 = regularize(u1, rho1) 
        #        wneg = (rho1<rhofloor) | (u1<ufloor)
        #        rho1[wneg] = rhofloor ; u1[wneg] = ufloor
        timer.stop_comp("toprim")
        timer.start_comp("flux")
        #        dul1 = diffuse(rho1, urad1, dl, across_half)
        s1, p1, fe1 = fluxes(rho1, v1, u1, across, r, sth)
        #        fe1 += -dul # adding diffusive flux 
        timer.stop_comp("flux")
        timer.start_comp("velocity")
        g1 = Gamma1(5./3., beta1)
        cs1=sqrt(g1 * press1/(rho1+0.*(u1+press1))) # slightly under-estimating the SOS to get stable signal velocities; exact for u << rho
        #        print("pressure1 = "+str(press1.min()))
        #        print("cs1 = "+str(cs1.min()))
        # vl, vm, vr = sigvel_toro(m1, s1, e1, p1, fe1, (v1-cs1)[:-1], (v1+cs1)[1:], across_half, r_half, sth_half)
        vl, vm, vr = sigvel_isentropic(v, cs, g1)
        # sigvel_linearized(v1, cs, g1, rho1, press1)
        timer.stop_comp("velocity")
        timer.start_comp("solver")
        s_half1, p_half1, fe_half1 = solv.HLLC([s1, p1, fe1], [m1, s1, e1], vl, vr, vm)
        # solv.HLLC([s1, p1, fe1], [m1, s1, e1], vl, vr, vm)
        dul_half1 = diffuse(rho1, urad1, dl, across_half)
        fe_half1 += dul_half1
        timer.stop_comp("solver")
        timer.start_comp("sources")
        dm1, ds1, de1, flux1, trat1 = sources(rho1, v1, u1, across, r, sth, cth, sina, cosa,ltot=ltot)
        ltot=simps(flux1, x=l) # no difference
        heat=simps(de1+flux1, x=l)
        timer.stop_comp("sources")
        timer.start_comp("main")
        m, s, e = main_step(m, s, e, l_half, s_half1, p_half1, fe_half1, dm1, ds1, de1, dt, r, sth, across, dlleft, dlright, g1)
        timer.stop_comp("main")
        timer.lap("step")
        t+=dt
        if(abs(s).max()>1e20):
            print("m is positive in "+str(sum(m>mfloor))+" points")
            print("s is positive in "+str(sum(abs(s)>mfloor))+" points")
            print("p is positive in "+str(sum(abs(p)>mfloor))+" points")
            winf=(abs(s)>1e20)
            print("t = "+str(t))
            print(r[winf]/rstar)
            print(m[winf])
            print(s[winf])
            print(e[winf])
            print(de[winf])
            print(flux[winf])
            if(ifhdf):
                hdf.close(hfile)
            ss=input('s')
        if(isnan(rho.max()) | (rho.max() > 1e20)):
            print(m)
            print(s)
            if(ifhdf):
                hdf.close(hfile)
            return(1)
        if(t>=tstore):
            timer.start("io")
            tstore+=dtout
            print("t = "+str(t*tscale)+"s")
            print("dt = "+str(dt))
            fflux.write(str(t*tscale)+' '+str(ltot)+' '+str(heat)+'\n')
            fflux.flush()
            #            oneplot(r, rho, name=outdir+'/rhotie{:05d}'.format(nout))
            if ifplot & (nout%plotalias == 0):
                print("plotting")
                plots.uplot(r, u, rho, sth, v, name=outdir+'/utie{:05d}'.format(nout))
                plots.vplot(r, v, sqrt(4./3.*u/rho), name=outdir+'/vtie{:05d}'.format(nout))
                plots.someplots(r, [u/rho**(4./3.)], name=outdir+'/entropy{:05d}'.format(nout), ytitle=r'$S$', ylog=True)
                plots.someplots(r, [(u-urad)/(u-urad/2.), 1.-(u-urad)/(u-urad/2.)],
                                name=outdir+'/beta{:05d}'.format(nout), ytitle=r'$\beta$, $1-\beta$', ylog=True)
            mtot=simps(m[1:-1], x=l[1:-1])
            etot=simps(e[1:-1], x=l[1:-1])
            print("mass = "+str(mtot))
            print("ltot = "+str(ltot))
            print("heat = "+str(heat))
            print("energy = "+str(etot))
            print("momentum = "+str(trapz(s[1:-1], x=l[1:-1])))
            
            ftot.write(str(t*tscale)+' '+str(mtot)+' '+str(etot)+'\n')
            ftot.flush()
            if(ifhdf):
                hdf.dump(hfile, nout, t, rho, v, u)
            if not(ifhdf) or (nout%ascalias == 0):
                # ascii output:
                print(nout)
                fname=outdir+'/tireout{:05d}'.format(nout)+'.dat'
                fstream=open(fname, 'w')
                fstream.write('# t = '+str(t*tscale)+'s\n')
                fstream.write('# format: r/rstar -- rho -- v -- u/umag\n')
                for k in arange(nx):
                    fstream.write(str(r[k]/rstar)+' '+str(rho[k])+' '+str(v[k])+' '+str(u[k]/umagtar[k])+'\n')
                fstream.close()
                #print simulation run-time statistics
            timer.stop("io")
            if(nout%ascalias == 0):
                timer.stats("step")
                timer.stats("io")
                timer.comp_stats()
                timer.start("step") #refresh lap counter (avoids IO profiling)
                timer.purge_comps()
   
            nout+=1
    fflux.close()
    ftot.close()
    if(ifhdf):
        hdf.close(hfile)
# if you want to make a movie of how the velocity changes with time:
# ffmpeg -f image2 -r 15 -pattern_type glob -i 'out/vtie*0.png' -pix_fmt yuv420p -b 4096k v.mp4
# alltire()
